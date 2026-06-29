"""
多智能体工业排障 RAG 系统 - 应用入口
LlamaIndex (RAG) + LangGraph (多智能体编排)
"""

import os
os.environ["PYTHONUTF8"] = "1"

import logging
import uuid
from contextvars import ContextVar

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pythonjsonlogger import json as jsonlogger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.endpoints import router
from api.limiter import limiter
from config.settings import settings

# ==================== 结构化日志 ====================

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class TraceFilter(logging.Filter):
    """将 trace_id 注入每条日志"""

    def filter(self, record):
        record.trace_id = trace_id_var.get("-")
        return True


def setup_logging():
    """配置 JSON 结构化日志"""
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(trace_id)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)
    handler.addFilter(TraceFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))


setup_logging()
logger = logging.getLogger(__name__)

# ==================== 应用 ====================

app = FastAPI(
    title="多智能体工业排障 RAG 系统",
    description="基于 LlamaIndex + LangGraph 的智能排障系统",
    version="2.0.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ==================== 中间件 ====================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """请求级 trace_id：从 header 读取或自动生成"""
    tid = request.headers.get("X-Trace-ID", str(uuid.uuid4())[:8])
    trace_id_var.set(tid)

    # 请求体大小限制
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.MAX_BODY_SIZE:
        return Response(
            content='{"detail":"请求体过大"}',
            status_code=413,
            media_type="application/json",
        )

    response = await call_next(request)
    response.headers["X-Trace-ID"] = tid
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """API Key 认证"""
    # 白名单路径
    open_paths = {"/", "/docs", "/openapi.json", "/redoc", "/api/health"}
    if request.url.path in open_paths:
        return await call_next(request)

    # 静态资源放行
    if request.url.path.startswith("/static/"):
        return await call_next(request)

    # 管理接口用 admin key
    if request.url.path == "/api/ingest":
        admin_key = settings.ADMIN_API_KEY
        if admin_key:
            provided = request.headers.get("X-API-Key", "")
            if provided != admin_key:
                return Response(
                    content='{"detail":"管理接口认证失败"}',
                    status_code=401,
                    media_type="application/json",
                )
        return await call_next(request)

    # 普通接口用 api key
    api_key = settings.API_KEY
    if api_key:
        provided = request.headers.get("X-API-Key", "")
        if provided != api_key:
            return Response(
                content='{"detail":"认证失败"}',
                status_code=401,
                media_type="application/json",
            )

    return await call_next(request)


# ==================== 路由 ====================

# 静态文件
app.mount("/static", StaticFiles(directory=str(settings.IMAGES_DIR)), name="static")

app.include_router(router)


@app.get("/")
async def root():
    return {
        "message": "多智能体工业排障 RAG 系统 v2.0",
        "architecture": "LlamaIndex (RAG) + LangGraph (Agents)",
        "docs": "/docs",
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
