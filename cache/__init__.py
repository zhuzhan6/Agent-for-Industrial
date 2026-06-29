"""
缓存模块 - 基于 Redis 的语义查询结果缓存
"""

from cache.query_cache import query_cache, QueryCache

__all__ = ["query_cache", "QueryCache"]
