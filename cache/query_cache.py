"""
语义查询结果缓存

基于 Redis 存储 + Embedding 余弦相似度匹配：
1. 精确匹配：SHA256(query) → 直接命中
2. 语义匹配：Embedding 余弦相似度 > 阈值 → 语义命中
3. 未命中：返回 None，由调用方执行完整流程后 store()

存储结构：
- cache:exact:{sha256_16}    → result_json (string, TTL)
- cache:entry:{uuid}         → Hash {query_text, result, embedding, created_at}
- cache:index                → ZSET {entry_id: timestamp}
"""

import hashlib
import json
import logging
import time
import uuid
from typing import Optional

import numpy as np
import redis

from config.settings import settings

logger = logging.getLogger(__name__)


class QueryCache:
    """语义查询结果缓存"""

    def __init__(
        self,
        redis_url: str = "",
        similarity_threshold: float = 0.92,
        ttl: int = 86400,
        max_candidates: int = 500,
    ):
        self.redis = redis.from_url(redis_url or settings.REDIS_URL)
        self.similarity_threshold = similarity_threshold
        self.ttl = ttl
        self.max_candidates = max_candidates
        self._embed_model = None
        self._hits = 0
        self._misses = 0

    @property
    def embed_model(self):
        """懒加载 Embedding 模型（复用 rag/index.py 的全局实例）"""
        if self._embed_model is None:
            from rag.index import get_embed_model

            self._embed_model = get_embed_model()
        return self._embed_model

    @staticmethod
    def _make_entry_key(entry_id: str) -> str:
        return f"cache:entry:{entry_id}"

    @staticmethod
    def _make_exact_key(query: str) -> str:
        query_hash = hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]
        return f"cache:exact:{query_hash}"

    # ==================== 查找 ====================

    def lookup(self, query: str) -> Optional[dict]:
        """
        查找缓存：先精确匹配，再语义匹配。

        Returns:
            命中时返回 cached_result dict，未命中返回 None
        """
        # ---- 1. 精确匹配 ----
        exact_key = self._make_exact_key(query)
        exact_data = self.redis.get(exact_key)
        if exact_data:
            self._hits += 1
            cached = json.loads(
                exact_data.decode() if isinstance(exact_data, bytes) else exact_data
            )
            logger.info(
                "[缓存] 精确命中 (%.1f%%)",
                self.hit_rate * 100,
                extra={"query": query[:60], "type": "exact"},
            )
            return cached

        # ---- 2. 语义匹配 ----
        try:
            query_embedding = self.embed_model.get_text_embedding(query)
        except Exception:
            logger.warning("[缓存] Embedding 编码失败，跳过语义查找")
            return None

        candidate_ids = self.redis.zrevrange(
            "cache:index", 0, self.max_candidates - 1
        )
        if not candidate_ids:
            self._misses += 1
            return None

        # 批量加载候选 embedding
        pipe = self.redis.pipeline()
        for cid in candidate_ids:
            cid_str = cid.decode() if isinstance(cid, bytes) else cid
            pipe.hget(self._make_entry_key(cid_str), "embedding")
        embeddings_raw = pipe.execute()

        # 计算余弦相似度
        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            self._misses += 1
            return None

        best_score = -1.0
        best_entry_id = None

        for cid, emb_raw in zip(candidate_ids, embeddings_raw):
            if emb_raw is None:
                continue
            cid_str = cid.decode() if isinstance(cid, bytes) else cid
            try:
                cached_emb = np.array(
                    json.loads(
                        emb_raw.decode() if isinstance(emb_raw, bytes) else emb_raw
                    ),
                    dtype=np.float32,
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

            cached_norm = np.linalg.norm(cached_emb)
            if cached_norm == 0:
                continue

            cosine_sim = float(np.dot(query_vec, cached_emb) / (query_norm * cached_norm))
            if cosine_sim > best_score:
                best_score = cosine_sim
                best_entry_id = cid_str

        if best_score >= self.similarity_threshold and best_entry_id:
            entry = self.redis.hgetall(self._make_entry_key(best_entry_id))
            if entry:
                result_raw = entry.get(b"result") or entry.get("result")
                if result_raw:
                    self._hits += 1
                    cached = json.loads(
                        result_raw.decode()
                        if isinstance(result_raw, bytes)
                        else result_raw
                    )
                    # 回填精确匹配索引，下次相同 query 直接命中
                    self.redis.setex(
                        exact_key,
                        self.ttl,
                        json.dumps(cached, ensure_ascii=False),
                    )
                    logger.info(
                        "[缓存] 语义命中 (sim=%.3f, hits=%.1f%%)",
                        best_score,
                        self.hit_rate * 100,
                        extra={"query": query[:60], "similarity": round(best_score, 4)},
                    )
                    return cached

        self._misses += 1
        logger.info(
            "[缓存] 未命中 (best_sim=%.3f, threshold=%.2f)",
            best_score,
            self.similarity_threshold,
            extra={"query": query[:60]},
        )
        return None

    # ==================== 存储 ====================

    def store(self, query: str, result: dict):
        """
        存储查询结果到缓存。

        Args:
            query: 原始查询文本
            result: 诊断结果 dict（可 JSON 序列化）
        """
        try:
            query_embedding = self.embed_model.get_text_embedding(query)
        except Exception:
            logger.warning("[缓存] Embedding 编码失败，跳过存储")
            return

        entry_id = str(uuid.uuid4())
        entry_key = self._make_entry_key(entry_id)

        entry_data = {
            "query_text": query,
            "result": json.dumps(result, ensure_ascii=False),
            "embedding": json.dumps(query_embedding),
            "created_at": str(time.time()),
        }

        pipe = self.redis.pipeline()
        pipe.hset(entry_key, mapping=entry_data)
        pipe.expire(entry_key, self.ttl)
        pipe.zadd("cache:index", {entry_id: time.time()})
        pipe.execute()

        # 精确匹配索引
        exact_key = self._make_exact_key(query)
        self.redis.setex(
            exact_key,
            self.ttl,
            json.dumps(result, ensure_ascii=False),
        )

        logger.info(
            "[缓存] 已存储 entry=%s query=%.60s",
            entry_id[:8],
            query,
        )

        # 概率清理过期条目（~10% 触发）
        if hash(entry_id) % 10 == 0:
            self._evict()

    # ==================== 维护 ====================

    def _evict(self):
        """淘汰超出上限的旧条目"""
        try:
            count = self.redis.zcard("cache:index")
            if count > self.max_candidates * 2:
                remove_count = count - self.max_candidates
                removed = self.redis.zremrangebyrank("cache:index", 0, remove_count - 1)
                logger.info("[缓存] 淘汰 %d 条旧缓存（当前 %d → 保留 %d）", removed, count, count - removed)
        except Exception:
            logger.warning("[缓存] 淘汰检查失败", exc_info=True)

    def clear(self):
        """清空所有查询缓存"""
        for pattern in ("cache:entry:*", "cache:exact:*"):
            keys = self.redis.keys(pattern)
            if keys:
                self.redis.delete(*keys)
        self.redis.delete("cache:index")
        self._hits = self._misses = 0
        logger.info("[缓存] 已清空")

    # ==================== 统计 ====================

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    @property
    def stats(self) -> dict:
        try:
            entry_count = self.redis.zcard("cache:index")
        except Exception:
            entry_count = -1
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 4),
            "entry_count": entry_count,
        }


# ---- 全局单例 ----
query_cache = QueryCache(
    redis_url=settings.REDIS_URL,
    similarity_threshold=settings.CACHE_SIMILARITY_THRESHOLD,
    ttl=settings.CACHE_TTL,
)
