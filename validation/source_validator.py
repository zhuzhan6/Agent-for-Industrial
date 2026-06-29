"""
出处验证服务
反幻觉校验：验证报告中引用的出处是否真实存在于知识库中
"""

import logging

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from config.settings import settings

logger = logging.getLogger(__name__)


class SourceValidator:
    """出处验证器"""

    def __init__(self):
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            self._client = QdrantClient(
                host=settings.QDRANT_HOST, port=settings.QDRANT_PORT
            )

    def validate_references(self, references: list[dict]) -> tuple[list[dict], bool]:
        """
        验证引用列表
        返回: (更新后的引用列表, 是否存在幻觉)
        """
        self._ensure_client()
        has_hallucination = False

        for ref in references:
            chunk_id = ref.get("chunk_id", "")
            source = ref.get("source", "")
            if not chunk_id:
                ref["verified"] = False
                has_hallucination = True
                continue

            # 按品牌拼接 collection 名（与 rag/index.py 一致）
            collection_name = f"{settings.QDRANT_COLLECTION}_{source}" if source else settings.QDRANT_COLLECTION
            exists = self._check_chunk_exists(chunk_id, collection_name)
            ref["verified"] = exists
            if not exists:
                has_hallucination = True

        return references, has_hallucination

    def _check_chunk_exists(self, chunk_id: str, collection_name: str) -> bool:
        """检查 chunk 是否存在于 Qdrant 指定 collection"""
        try:
            results = self._client.scroll(
                collection_name=collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="chunk_id", match=MatchValue(value=chunk_id)
                        )
                    ]
                ),
                limit=1,
            )
            return len(results[0]) > 0
        except Exception as e:
            logger.warning("出处验证查询失败", extra={"chunk_id": chunk_id, "collection": collection_name, "error": str(e)})
            return False


source_validator = SourceValidator()
