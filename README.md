# 多智能体工业排障 RAG 系统

基于 **LlamaIndex RAG + LangGraph 多智能体编排** 的工业设备智能诊断与排障系统。支持 FANUC、Siemens 840D、VMC850 等数控设备的故障诊断，具备追问推理、复合故障分析、SSE 流式输出等功能。

## 🏗️ 架构

```
┌─────────────────────────────────────────────────┐
│                    用户界面 (Vue 3)                │
│                  http://localhost:8080            │
└──────────────────────┬──────────────────────────┘
                       │ SSE / REST
┌──────────────────────▼──────────────────────────┐
│                  Nginx (反向代理)                  │
│         静态文件 + API 代理 + SSE 缓冲关闭          │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│              FastAPI 后端 (:8000)                  │
│  ┌──────────────────────────────────────────┐   │
│  │         LangGraph 多智能体编排              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌───────┐   │   │
│  │  │ 分诊专家  │  │ FANUC专家 │  │Siemens│   │   │
│  │  │ (路由器)  │→ │          │  │ 专家  │   │   │
│  │  └──────────┘  └──────────┘  └───────┘   │   │
│  └──────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────┐   │
│  │           LlamaIndex RAG 管道              │   │
│  │   稠密检索 + BM25 + RRF融合 + 重排序        │   │
│  └──────────────────────────────────────────┘   │
└──────┬───────────────────┬──────────────────────┘
       │                   │
┌──────▼──────┐   ┌────────▼────────┐
│   Qdrant    │   │     Redis       │
│  向量数据库  │   │  会话 / 缓存    │
└─────────────┘   └─────────────────┘
```

## ✨ 特性

- **多智能体编排** — LangGraph 实现分诊路由 + 品牌专家并行诊断
- **混合检索** — 稠密向量 (BGE) + BM25 关键词 + RRF 融合 + 交叉编码器重排序
- **智能追问** — 信息不足时自动追问，最多 2 轮，支持复合故障同时分配双专家
- **SSE 流式输出** — 前端逐字显示诊断结果
- **缓存加速** — 语义相似查询命中缓存直接返回
- **来源追溯** — 每个诊断结论附带知识库来源引用
- **Docker 一键部署** — 全容器化，5 个服务编排启动

## 📦 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 智能体编排 | LangGraph |
| RAG 管道 | LlamaIndex |
| LLM | MIMO v2.5 (OpenAI 兼容 API) |
| 嵌入模型 | BGE-Large-zh-v1.5 (1024d) |
| 重排序 | BGE-Reranker-Large |
| 向量数据库 | Qdrant |
| 缓存 / 会话 | Redis |
| 前端 | Vue 3 + Vite + Element Plus |
| Markdown 渲染 | marked |
| 反向代理 | Nginx |

## 🚀 快速开始 (Docker)

### 前置条件

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose v2
- 本地模型文件：`models/BAAI/bge-large-zh-v1___5/` 和 `models/BAAI/bge-reranker-large/`（共约 7.5 GB）
- `.env` 配置文件（LLM API Key 等）
- （可选）GPU 加速需安装 [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

### 1. 准备环境

```bash
# 确保 .env 文件存在并配置正确
cp .env.example .env   # 如有模板
vim .env               # 填入 LLM_API_KEY 等配置

# 确保模型目录存在
ls models/BAAI/bge-large-zh-v1___5/
ls models/BAAI/bge-reranker-large/
```

### 2. 启动全部服务

```bash
# CPU 模式
docker compose up -d

# GPU 模式（需 nvidia-container-toolkit）
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

首次启动会自动执行数据注入（ingest），将知识库索引到 Qdrant。

### 3. 验证

```bash
# 检查服务状态
docker compose ps

# 查看后端日志
docker compose logs backend

# 查看注入日志
docker compose logs ingest

# 健康检查
curl http://localhost:8080/api/health
```

### 4. 访问

- **前端界面**: http://localhost:8080
- **API 文档**: http://localhost:8000/docs
- **Qdrant Dashboard**: http://localhost:6333/dashboard

### 5. 常用命令

```bash
docker compose up -d              # 启动
docker compose down               # 停止
docker compose restart backend    # 重启后端
docker compose logs -f backend    # 实时查看日志
docker compose --profile gpu build  # 重新构建镜像
```

## 🛠️ 本地开发

```bash
# 后端
pip install -r requirements.txt
PYTHONUTF8=1 uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd frontend && npm install && npm run dev

# 数据注入（首次或知识库更新后）
PYTHONUTF8=1 python ingest.py --force
```

## ⚙️ 配置说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_API_KEY` | — | LLM API 密钥 (必填) |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `LLM_MODEL` | `gpt-4o` | LLM 模型名称 |
| `QDRANT_HOST` | `localhost` | Qdrant 主机 |
| `QDRANT_PORT` | `6333` | Qdrant 端口 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接 |
| `EMBEDDING_DEVICE` | `cpu` | 嵌入模型设备 (cpu/cuda) |
| `RERANKER_TOP_K` | `5` | 重排序返回数量 |
| `CACHE_TTL` | `86400` | 查询缓存 TTL (秒) |
| `API_KEY` | — | API 认证密钥 (可选) |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `MAX_FOLLOWUP_COUNT` | `2` | 最大追问次数 |

完整配置见 `config/settings.py`。

## 📁 项目结构

```
.
├── main.py                    # 应用入口
├── ingest.py                  # 数据注入脚本
├── requirements.txt           # Python 依赖
├── nginx.conf                 # Nginx 配置
├── docker-compose.yml         # Docker 编排
├── docker-compose.gpu.yml     # GPU 覆盖配置
├── Dockerfile.backend         # 后端镜像
├── Dockerfile.frontend        # 前端镜像
│
├── agents/                    # 智能体模块
│   ├── graph.py               # LangGraph 图定义
│   ├── nodes.py               # 图节点 (分诊/诊断/追问)
│   ├── state.py               # 状态定义
│   ├── tools.py               # Agent 工具
│   └── streaming.py           # 流式输出支持
│
├── rag/                       # RAG 管道
│   ├── index.py               # Qdrant 索引管理
│   ├── retriever.py           # 混合检索器
│   ├── bm25_retriever.py      # BM25 检索
│   └── parsers/               # 知识库解析器
│       ├── fanuc_parser.py
│       ├── siemens_parser.py
│       └── vmc_parser.py
│
├── api/                       # API 层
│   ├── endpoints.py           # REST 端点
│   ├── limiter.py             # 速率限制
│   └── session.py             # 会话管理
│
├── config/                    # 配置
│   └── settings.py            # 全局配置 (pydantic-settings)
│
├── cache/                     # 查询缓存
│   └── query_cache.py
│
├── validation/                # 来源验证
│   └── source_validator.py
│
├── iot/                       # IoT 接口 (预留)
├── maintenance/               # 维保接口 (预留)
│
├── frontend/                  # Vue 3 前端
│   └── src/
│       ├── App.vue
│       ├── views/             # 页面
│       ├── components/        # 组件
│       ├── api/               # API 调用
│       └── stores/            # 状态管理
│
├── images/                    # 诊断图片 (107 MB)
├── models/BAAI/               # 本地模型 (不进入 Git/Docker 镜像)
├── *.md                       # 知识库源文件
└── qdrant_data/               # Qdrant 持久化数据
```

## 📄 API 文档

启动后端后访问 http://localhost:8000/docs 查看 Swagger UI。

主要端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 + 索引状态 |
| `POST` | `/api/diagnose` | 同步诊断 |
| `POST` | `/api/diagnose/stream` | SSE 流式诊断 |
| `GET` | `/api/session/{id}/history` | 对话历史 |
| `POST` | `/api/ingest` | 数据注入 (需 Admin API Key) |

## 📝 License

MIT
