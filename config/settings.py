"""
全局配置管理
"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ==================== 项目路径 ====================
    PROJECT_ROOT: Path = Path(__file__).parent.parent
    DATA_DIR: Path = PROJECT_ROOT
    IMAGES_DIR: Path = PROJECT_ROOT / "images"

    # ==================== Qdrant ====================
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "industrial_troubleshooting"
    QDRANT_VECTOR_SIZE: int = 1024  # bge-large-zh-v1.5
    QDRANT_MODE: str = "local"  # "local" 或 "remote"
    QDRANT_LOCAL_PATH: str = "./qdrant_data"  # 本地模式存储路径

    # ==================== Redis ====================
    REDIS_URL: str = "redis://localhost:6379/0"

    # ==================== 查询缓存 ====================
    CACHE_SIMILARITY_THRESHOLD: float = 0.92  # 语义匹配余弦相似度阈值
    CACHE_TTL: int = 86400  # 缓存过期时间（秒），默认24小时

    # ==================== Embedding ====================
    EMBEDDING_MODEL_NAME: str = "models/BAAI/bge-large-zh-v1___5"
    EMBEDDING_DEVICE: str = "cpu"

    # ==================== Reranker ====================
    RERANKER_MODEL_NAME: str = "models/BAAI/bge-reranker-large"
    RERANKER_TOP_K: int = 5

    # ==================== 检索 ====================
    RETRIEVAL_TOP_K: int = 20
    # 稠密向量召回置信度阈值
    DENSE_CONFIDENCE_THRESHOLD: float = 0.5
    # 交叉编码器重排序后置信度阈值
    RERANKER_CONFIDENCE_THRESHOLD: float = 0.3
    # BM25 检索数量
    BM25_TOP_K: int = 20
    # RRF 融合参数
    RRF_K: int = 60  # RRF 公式中的常数

    # ==================== LLM (OpenAI 兼容) ====================
    LLM_API_KEY: str = "your-api-key-here"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096

    # ==================== 文档源 ====================
    SOURCE_FILES: dict = {
        "fanuc": "fanuc.md",
        "siemens": "siemens_840D.md",
        "vmc850": "VMC850.md",
    }

    # ==================== 工厂品牌配置 ====================
    # 工厂已有的设备品牌列表，用于路由判断
    FACTORY_BRANDS: list[str] = ["FANUC", "SIEMENS"]

    # ==================== 追问配置 ====================
    # 最大追问次数（品牌1次 + 专家1次 = 2次）
    MAX_FOLLOWUP_COUNT: int = 2

    # ==================== Nginx ====================
    STATIC_BASE_URL: str = "http://localhost:8080/static"

    # ==================== API 认证 ====================
    API_KEY: str = ""  # 普通接口密钥，为空则跳过认证
    ADMIN_API_KEY: str = ""  # 管理接口密钥（ingest），为空则跳过认证

    # ==================== 日志 ====================
    LOG_LEVEL: str = "INFO"

    # ==================== 限流 ====================
    RATE_LIMIT_DIAGNOSE: str = "10/minute"
    RATE_LIMIT_INGEST: str = "2/minute"

    # ==================== 请求体 ====================
    MAX_BODY_SIZE: int = 10240  # 10KB

    # ==================== LLM 重试 ====================
    LLM_MAX_RETRIES: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
