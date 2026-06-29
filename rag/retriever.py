"""
LlamaIndex 检索器
整合向量检索 + BM25 + RRF 融合 + 置信度过滤 + bge-reranker 精排
"""

import logging

from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.schema import NodeWithScore

from config.settings import settings
from rag.index import get_index, get_embed_model
from rag.bm25_retriever import bm25_retrieve
from models.schemas import RetrievalResult

logger = logging.getLogger(__name__)

_reranker = None


def rrf_fusion(
    dense_results: list[NodeWithScore],
    bm25_results: list[NodeWithScore],
    k: int = 60,
) -> list[NodeWithScore]:
    """
    Reciprocal Rank Fusion (RRF) 融合
    将稠密向量检索和 BM25 检索的排名按 1/(k+rank) 公式合并
    """
    dense_ranks = {}
    for rank, node_with_score in enumerate(dense_results):
        dense_ranks[node_with_score.node.node_id] = rank

    bm25_ranks = {}
    for rank, node_with_score in enumerate(bm25_results):
        bm25_ranks[node_with_score.node.node_id] = rank

    rrf_scores: dict[str, float] = {}
    all_nodes: dict[str, NodeWithScore] = {}

    for node_with_score in dense_results:
        node_id = node_with_score.node.node_id
        all_nodes[node_id] = node_with_score
        rrf_scores.setdefault(node_id, 0.0)

    for node_with_score in bm25_results:
        node_id = node_with_score.node.node_id
        all_nodes.setdefault(node_id, node_with_score)
        rrf_scores.setdefault(node_id, 0.0)

    for node_id in rrf_scores:
        if node_id in dense_ranks:
            rrf_scores[node_id] += 1.0 / (k + dense_ranks[node_id])
        if node_id in bm25_ranks:
            rrf_scores[node_id] += 1.0 / (k + bm25_ranks[node_id])

    sorted_nodes = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    results = [
        NodeWithScore(node=all_nodes[node_id].node, score=score)
        for node_id, score in sorted_nodes
    ]

    logger.info(f"RRF 融合完成: 稠密 {len(dense_results)} + BM25 {len(bm25_results)} -> {len(results)} 个结果")
    return results


def get_reranker() -> SentenceTransformerRerank:
    """获取精排模型（懒加载）"""
    global _reranker
    if _reranker is None:
        _reranker = SentenceTransformerRerank(
            model=settings.RERANKER_MODEL_NAME,
            top_n=settings.RERANKER_TOP_K,
            device="cpu",  # GTX 1650 4GB 显存不足同时跑 Embedding + Reranker
        )
    return _reranker


def retrieve(
    query: str,
    source: str,
    top_k: int | None = None,
    use_reranker: bool = True,
) -> list[RetrievalResult]:
    """
    完整检索流程：
    1. 稠密向量检索（LlamaIndex）
    2. BM25 检索
    3. RRF 融合
    4. 稠密向量置信度过滤
    5. bge-reranker 精排
    6. 重排序后置信度过滤
    7. 返回带出处的结果
    """
    top_k = top_k or settings.RETRIEVAL_TOP_K
    index = get_index(source)

    # 1. 稠密向量检索
    retriever = index.as_retriever(similarity_top_k=top_k)
    dense_nodes = retriever.retrieve(query)
    logger.info(f"稠密向量检索命中 {len(dense_nodes)} 个节点")

    # 2. 稠密向量置信度过滤（第一处置信度阈值）
    dense_filtered = [
        n for n in dense_nodes
        if n.score is not None and n.score >= settings.DENSE_CONFIDENCE_THRESHOLD
    ]
    logger.info(f"稠密向量置信度过滤后 {len(dense_filtered)} 个节点 (阈值: {settings.DENSE_CONFIDENCE_THRESHOLD})")

    # 3. BM25 检索
    bm25_nodes = bm25_retrieve(
        source=source,
        query=query,
        top_k=settings.BM25_TOP_K,
    )

    # 4. RRF 融合
    if bm25_nodes:
        fused_nodes = rrf_fusion(
            dense_results=dense_filtered,
            bm25_results=bm25_nodes,
            k=settings.RRF_K,
        )
    else:
        fused_nodes = dense_filtered
        logger.info("BM25 无结果，使用稠密向量结果")

    if not fused_nodes:
        return []

    # 5. 精排
    if use_reranker and len(fused_nodes) > 1:
        reranker = get_reranker()
        reranked = reranker.postprocess_nodes(fused_nodes, query_str=query)
        logger.info(f"精排后 {len(reranked)} 个节点")

        # 6. 重排序后置信度过滤（仅精排模式下生效）
        final_nodes = [
            n for n in reranked
            if n.score is None or n.score >= settings.RERANKER_CONFIDENCE_THRESHOLD
        ]
        logger.info(f"重排序置信度过滤后 {len(final_nodes)} 个节点 (阈值: {settings.RERANKER_CONFIDENCE_THRESHOLD})")

        if not final_nodes:
            # 兜底：过滤后为0时，返回精排结果中分数最高的1条
            final_nodes = reranked[:1]
            logger.warning("精排过滤后为0，使用精排Top-1作为兜底")
    else:
        # 跳过精排，直接使用 RRF 融合结果（已通过稠密置信度过滤）
        final_nodes = fused_nodes
        logger.info(f"跳过精排，使用 RRF 融合结果 {len(final_nodes)} 个节点")

    # 7. 构建结果
    results = []
    for node_with_score in final_nodes:
        node = node_with_score.node
        metadata = node.metadata or {}

        # 解析图片
        images_str = metadata.get("images", "")
        images = [i.strip() for i in images_str.split(",") if i.strip()] if images_str else []
        parent_images_str = metadata.get("parent_images", "")
        parent_images = (
            [i.strip() for i in parent_images_str.split(",") if i.strip()]
            if parent_images_str
            else []
        )

        results.append(
            RetrievalResult(
                chunk_id=metadata.get("chunk_id", node.id_),
                text=node.get_content(),
                source=metadata.get("source", ""),
                section_title=metadata.get("section_title", ""),
                alarm_code=metadata.get("alarm_code") or "",
                images=images,
                score=node_with_score.score or 0.0,
                parent_text=metadata.get("parent_text", ""),
                parent_images=parent_images,
            )
        )

    return results
