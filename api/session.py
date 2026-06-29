"""
Redis 会话管理
"""

import json
import uuid
import logging

import redis

logger = logging.getLogger(__name__)


class SessionManager:
    """Redis 会话管理"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", ttl: int = 3600):
        self.redis = redis.from_url(redis_url)
        self.ttl = ttl  # 会话过期时间（秒）

    def create_session(self) -> str:
        """创建新会话，返回 session_id"""
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "messages": [],
            "graph_state": None,
        }
        self.redis.setex(f"session:{session_id}", self.ttl, json.dumps(session_data))
        logger.info(f"创建会话: {session_id}")
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        """获取会话数据"""
        data = self.redis.get(f"session:{session_id}")
        if data:
            return json.loads(data)
        return None

    def update_session(self, session_id: str, session_data: dict):
        """更新会话数据"""
        self.redis.setex(f"session:{session_id}", self.ttl, json.dumps(session_data))

    def add_message(self, session_id: str, role: str, content: str):
        """添加消息到对话历史"""
        session = self.get_session(session_id)
        if session:
            session["messages"].append({
                "role": role,
                "content": content,
            })
            self.update_session(session_id, session)

    def get_conversation_history(self, session_id: str) -> list[dict]:
        """获取对话历史"""
        session = self.get_session(session_id)
        if session:
            return session.get("messages", [])
        return []

    def save_graph_state(self, session_id: str, state: dict):
        """保存 LangGraph 状态"""
        session = self.get_session(session_id)
        if session:
            session["graph_state"] = state
            self.update_session(session_id, session)

    def get_graph_state(self, session_id: str) -> dict | None:
        """获取 LangGraph 状态"""
        session = self.get_session(session_id)
        if session:
            return session.get("graph_state")
        return None


# 全局单例
from config.settings import settings
session_manager = SessionManager(redis_url=settings.REDIS_URL)
