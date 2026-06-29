"""
LlamaIndex 索引管理
负责向量索引的构建和加载（Qdrant 后端）
按品牌建立不同的 collection
"""

import logging
import uuid
from pathlib import Path

from llama_index.core import Document, VectorStoreIndex, StorageContext
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from config.settings import settings

logger = logging.getLogger(__name__)

# ==================== 全局状态 ====================
_embed_model = None
_vector_stores = {}  # 按品牌存储不同的 vector store
_indices = {}  # 按品牌存储不同的 index


def get_embed_model() -> HuggingFaceEmbedding:
    """获取嵌入模型（懒加载）"""
    global _embed_model
    if _embed_model is None:
        _embed_model = HuggingFaceEmbedding(
            model_name=settings.EMBEDDING_MODEL_NAME,
            device=settings.EMBEDDING_DEVICE,
        )
    return _embed_model


def _create_qdrant_client() -> QdrantClient:
    """根据配置创建 Qdrant 客户端（本地或远程）"""
    if settings.QDRANT_MODE == "local":
        return QdrantClient(path=settings.QDRANT_LOCAL_PATH)
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)


def _get_collection_name(source: str) -> str:
    """根据品牌获取 collection 名称"""
    return f"{settings.QDRANT_COLLECTION}_{source}"


def get_vector_store(source: str) -> QdrantVectorStore:
    """获取指定品牌的 Qdrant 向量存储（懒加载）"""
    global _vector_stores
    if source not in _vector_stores:
        client = _create_qdrant_client()
        collection_name = _get_collection_name(source)
        _vector_stores[source] = QdrantVectorStore(
            client=client,
            collection_name=collection_name,
        )
    return _vector_stores[source]


def get_index(source: str) -> VectorStoreIndex:
    """获取指定品牌的索引（懒加载）"""
    global _indices
    if source not in _indices:
        vector_store = get_vector_store(source)
        embed_model = get_embed_model()
        _indices[source] = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=embed_model,
        )
    return _indices[source]


def build_index(chunks: list[dict], source: str, force_rebuild: bool = False):
    """
    从解析后的分块构建向量索引
    chunks: 解析器输出的分块列表
    source: 品牌标识（fanuc/siemens/vmc850）
    """
    client = _create_qdrant_client()
    collection_name = _get_collection_name(source)

    # 重建集合
    if force_rebuild:
        try:
            client.delete_collection(collection_name)
            logger.info(f"已删除旧集合: {collection_name}")
        except Exception:
            pass

    # 确保集合存在
    collections = client.get_collections().collections
    exists = any(c.name == collection_name for c in collections)
    if not exists:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=settings.QDRANT_VECTOR_SIZE, distance=Distance.COSINE
            ),
        )
        logger.info(f"已创建新集合: {collection_name}")

    # 只索引子块（检索入口），父块信息存在 metadata 中
    child_chunks = [c for c in chunks if c["chunk_type"] == "child"]

    # 构建 LlamaIndex Document
    documents = []
    for chunk in child_chunks:
        # 找到对应的父块
        parent_text = ""
        parent_images = []
        if chunk.get("parent_id"):
            parent = next(
                (c for c in chunks if c["chunk_id"] == chunk["parent_id"]), None
            )
            if parent:
                parent_text = parent["text"]
                parent_images = parent.get("images", [])

        # 将字符串 chunk_id 转换为 UUID（Qdrant 要求 integer 或 UUID）
        doc_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk["chunk_id"]))

        doc = Document(
            text=chunk["text"],
            metadata={
                "chunk_id": chunk["chunk_id"],
                "parent_id": chunk.get("parent_id", ""),
                "source": chunk["source"],
                "section_title": chunk.get("section_title", ""),
                "alarm_code": chunk.get("alarm_code", ""),
                "level1_tag": chunk.get("level1_tag", ""),
                "level2_category": chunk.get("level2_category", ""),
                "images": ",".join(chunk.get("images", [])),
                "parent_images": ",".join(parent_images),
            },
            id_=doc_uuid,
        )
        documents.append(doc)

    logger.info(f"准备索引 {len(documents)} 个子块文档到 {collection_name}")

    # 构建索引
    vector_store = get_vector_store(source)
    embed_model = get_embed_model()

    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex(
        nodes=documents,
        storage_context=storage_context,
        embed_model=embed_model,
        show_progress=True,
    )

    # 更新全局索引
    global _indices
    _indices[source] = index

    logger.info(f"索引构建完成，共 {len(documents)} 个文档，集合: {collection_name}")
    return index


def build_all_indices(chunks_by_source: dict[str, list[dict]], force_rebuild: bool = False):
    """
    构建所有品牌的索引
    chunks_by_source: {source: chunks} 字典
    """
    for source, chunks in chunks_by_source.items():
        logger.info(f"开始构建 {source} 索引...")
        build_index(chunks, source, force_rebuild)
    logger.info("所有索引构建完成")
