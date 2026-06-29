"""
BM25 检索器
用于与稠密向量检索进行 RRF 融合
"""

import logging
import re

from rank_bm25 import BM25Okapi
from llama_index.core.schema import NodeWithScore, TextNode

logger = logging.getLogger(__name__)

# 全局 BM25 索引缓存
_bm25_indices: dict[str, BM25Okapi] = {}
_node_cache: dict[str, list[TextNode]] = {}


def _tokenize(text: str) -> list[str]:
    """中文分词（简单实现，按字符和标点分割）"""
    # 移除标点符号，按空格和中文字符分割
    text = re.sub(r'[^\w\s一-鿿]', ' ', text)
    # 中文按字符分割，英文按空格分割
    tokens = []
    for char in text:
        if '一' <= char <= '鿿':
            tokens.append(char)
        elif char.isalnum():
            tokens.append(char.lower())
    return tokens


def build_bm25_index(source: str, nodes: list[TextNode]):
    """
    为指定品牌构建 BM25 索引
    """
    global _bm25_indices, _node_cache

    if not nodes:
        logger.warning(f"没有节点可用于构建 BM25 索引: {source}")
        return

    # 提取文本并分词
    corpus = [_tokenize(node.get_content()) for node in nodes]

    # 构建 BM25 索引
    bm25 = BM25Okapi(corpus)
    _bm25_indices[source] = bm25
    _node_cache[source] = nodes

    logger.info(f"BM25 索引构建完成: {source}, 共 {len(nodes)} 个文档")


def bm25_retrieve(
    source: str,
    query: str,
    top_k: int = 20,
) -> list[NodeWithScore]:
    """
    BM25 检索
    """
    if source not in _bm25_indices:
        logger.warning(f"BM25 索引不存在: {source}")
        return []

    bm25 = _bm25_indices[source]
    nodes = _node_cache[source]

    # 分词查询
    query_tokens = _tokenize(query)

    # BM25 检索
    scores = bm25.get_scores(query_tokens)

    # 获取 top_k 结果
    top_indices = scores.argsort()[-top_k:][::-1]

    results = []
    for idx in top_indices:
        if scores[idx] > 0:  # 只返回有相关性的结果
            results.append(
                NodeWithScore(
                    node=nodes[idx],
                    score=float(scores[idx]),
                )
            )

    logger.info(f"BM25 检索命中 {len(results)} 个节点: {source}")
    return results


