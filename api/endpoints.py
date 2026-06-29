"""
FastAPI 路由
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from agents.graph import get_compiled_graph
from agents.state import AgentState
from agents.streaming import stream_diagnosis
from api.session import session_manager
from config.settings import settings
from api.limiter import limiter
from cache.query_cache import query_cache
from models.schemas import (
    DiagnoseRequest,
    DiagnoseResponse,
    HealthResponse,
    ImageInfo,
    IngestRequest,
)
from validation.source_validator import source_validator

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/diagnose", response_model=DiagnoseResponse)
@limiter.limit(settings.RATE_LIMIT_DIAGNOSE)
async def diagnose(request: Request, body: DiagnoseRequest):
    """
    主诊断接口（支持多轮对话）
    完整流程：LangGraph 路由 → 专家诊断（含 IoT function calling）→ [追问] → 报告 → 出处验证
    """
    try:
        query = body.query.strip()
        if not query:
            raise HTTPException(status_code=400, detail="查询内容不能为空")

        # 获取或创建会话
        session_id = body.session_id
        if session_id:
            session = session_manager.get_session(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="会话不存在或已过期")
        else:
            session_id = session_manager.create_session()

        # 保存用户消息
        session_manager.add_message(session_id, "user", query)

        # 获取对话历史（用于上下文拼接）
        conversation_history = session_manager.get_conversation_history(session_id)
        graph_state = session_manager.get_graph_state(session_id)

        # 如果是追问回复，拼接之前的上下文（追问不查缓存）
        is_followup = bool(graph_state and graph_state.get("pending_followup"))
        full_query = query
        if is_followup:
            original_query = graph_state.get("original_query", "")
            followup_context = graph_state.get("followup_context", "")
            full_query = f"{original_query}\n专家追问：{followup_context}\n用户补充：{query}"
            # 清除追问状态
            session_manager.save_graph_state(session_id, {})

        # ========== 查询缓存（非追问场景） ==========
        cache_hit = False
        if not is_followup:
            cached = query_cache.lookup(full_query)
            if cached:
                cache_hit = True
                logger.info("缓存命中，直接返回", extra={"query": query[:60], "session_id": session_id})

                # 图片 URL 拼接
                cache_images = cached.get("images", [])
                cache_image_urls = [
                    f"{settings.STATIC_BASE_URL}/{img.lstrip('images/')}" if not img.startswith("http") else img
                    for img in cache_images
                ]
                cache_image_details = [
                    ImageInfo(**img) if isinstance(img, dict) else img
                    for img in cached.get("image_details", [])
                ]
                # 修正 image_details 中的 path
                for img_detail in cache_image_details:
                    raw_path = img_detail.path
                    if raw_path and not raw_path.startswith("http"):
                        img_detail.path = f"{settings.STATIC_BASE_URL}/{raw_path.lstrip('images/')}"

                response = DiagnoseResponse(
                    session_id=session_id,
                    question=query,
                    summary=cached.get("summary", ""),
                    cause_analysis=cached.get("cause_analysis", ""),
                    solution_steps=cached.get("solution_steps", []),
                    references=cached.get("references", []),
                    images=cache_image_urls,
                    image_details=cache_image_details,
                    iot_data=cached.get("iot_data"),
                    confidence=cached.get("confidence", 0.0),
                    has_hallucination=cached.get("has_hallucination", False),
                    router_decision=cached.get("router_decision", {}),
                    needs_followup=cached.get("needs_followup", False),
                    followup_question=cached.get("followup_question", ""),
                )
                session_manager.add_message(session_id, "assistant", cached.get("summary", ""))
                return response

        # ========== 执行 LangGraph（缓存未命中） ==========
        # 构建初始状态
        followup_count = graph_state.get("followup_count", 0) if graph_state else 0
        initial_state: AgentState = {
            "query": full_query,
            "intent": "",
            "fault_type": "",
            "target_agent": "",
            "source": "",  # Router 会判断品牌
            "router_reasoning": "",
            "retrieval_results": [],
            "iot_data": None,
            "expert_analysis": "",
            "expert_source": "",
            "expert_confidence": 0.0,
            "needs_followup": False,
            "followup_question": "",
            "followup_count": followup_count,
            "conversation_history": conversation_history,
            "summary": "",
            "cause_analysis": "",
            "solution_steps": [],
            "references": [],
            "images": [],
            "image_details": [],
            "has_hallucination": False,
            "messages": [],
        }

        logger.info("收到诊断请求", extra={"query": query, "session_id": session_id, "cache_hit": False})
        compiled_graph = get_compiled_graph()
        final_state = compiled_graph.invoke(initial_state)

        # 检查是否需要追问
        if final_state.get("needs_followup"):
            followup_q = final_state.get("followup_question", "请提供更多信息")
            # 保存追问状态（包括追问次数）
            session_manager.save_graph_state(session_id, {
                "pending_followup": True,
                "original_query": query,
                "followup_context": followup_q,
                "followup_count": final_state.get("followup_count", 0),
            })
            session_manager.add_message(session_id, "assistant", followup_q)

            return DiagnoseResponse(
                session_id=session_id,
                question=query,
                needs_followup=True,
                followup_question=followup_q,
            )

        # 闲聊处理
        if final_state.get("intent") == "chitchat":
            chitchat_reply = "你好！我是工业排障助手，请描述您遇到的设备故障或报警代码，我将为您智能诊断。"
            response = DiagnoseResponse(
                session_id=session_id,
                question=query,
                summary=chitchat_reply,
                cause_analysis=chitchat_reply,
                router_decision={
                    "intent": "chitchat",
                    "reasoning": final_state.get("router_reasoning", ""),
                },
            )
            session_manager.add_message(session_id, "assistant", chitchat_reply)
            return response

        # 出处验证
        references = final_state.get("references", [])
        if references:
            references, has_hallucination = source_validator.validate_references(references)
        else:
            has_hallucination = False

        # 图片 URL 拼接
        images = final_state.get("images", [])
        image_urls = [
            f"{settings.STATIC_BASE_URL}/{img.lstrip('images/')}" if not img.startswith("http") else img
            for img in images
        ]

        # 结构化图片信息
        image_details_raw = final_state.get("image_details", [])
        image_details = []
        for img_info in image_details_raw:
            # 支持 dict 和 ImageInfo 对象两种格式
            if isinstance(img_info, dict):
                raw_path = img_info.get("path", "")
                alt = img_info.get("alt", "")
                desc = img_info.get("description", "")
            else:
                raw_path = img_info.path if hasattr(img_info, 'path') else ""
                alt = img_info.alt if hasattr(img_info, 'alt') else ""
                desc = img_info.description if hasattr(img_info, 'description') else ""
            url = f"{settings.STATIC_BASE_URL}/{raw_path.lstrip('images/')}" if raw_path and not raw_path.startswith("http") else raw_path
            image_details.append(ImageInfo(
                path=url,
                alt=alt,
                description=desc,
            ))

        router_decision = {
            "intent": final_state.get("intent", ""),
            "fault_type": final_state.get("fault_type", ""),
            "target_agent": final_state.get("target_agent", ""),
            "reasoning": final_state.get("router_reasoning", ""),
        }

        response = DiagnoseResponse(
            session_id=session_id,
            question=query,
            summary=final_state.get("summary", ""),
            cause_analysis=final_state.get("cause_analysis", ""),
            solution_steps=final_state.get("solution_steps", []),
            references=references,
            images=image_urls,
            image_details=image_details,
            iot_data=final_state.get("iot_data"),
            confidence=final_state.get("expert_confidence", 0.0),
            has_hallucination=has_hallucination,
            router_decision=router_decision,
        )

        # 保存助手回复
        session_manager.add_message(session_id, "assistant", final_state.get("summary", ""))

        # ========== 存储缓存（非追问场景 + 非闲聊） ==========
        if not is_followup and not cache_hit and final_state.get("summary"):
            try:
                # 存储原始路径（不含 STATIC_BASE_URL），下次命中时再拼接
                cache_images_raw = final_state.get("images", [])
                cache_image_details_raw = []
                for img_info in image_details_raw:
                    if isinstance(img_info, dict):
                        cache_image_details_raw.append(img_info)
                    else:
                        cache_image_details_raw.append({
                            "path": img_info.path if hasattr(img_info, 'path') else "",
                            "alt": img_info.alt if hasattr(img_info, 'alt') else "",
                            "description": img_info.description if hasattr(img_info, 'description') else "",
                        })

                query_cache.store(full_query, {
                    "query": query,
                    "summary": final_state.get("summary", ""),
                    "cause_analysis": final_state.get("cause_analysis", ""),
                    "solution_steps": final_state.get("solution_steps", []),
                    "references": references,
                    "images": cache_images_raw,
                    "image_details": cache_image_details_raw,
                    "iot_data": final_state.get("iot_data"),
                    "confidence": final_state.get("expert_confidence", 0.0),
                    "has_hallucination": has_hallucination,
                    "router_decision": router_decision,
                    "needs_followup": False,
                    "followup_question": "",
                })
            except Exception:
                logger.warning("缓存存储失败", exc_info=True)

        return response

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error("诊断失败", extra={"error": str(e), "traceback": traceback.format_exc()})
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/diagnose/stream")
@limiter.limit(settings.RATE_LIMIT_DIAGNOSE)
async def diagnose_stream(request: Request, body: DiagnoseRequest):
    """
    流式诊断接口（SSE）
    实时返回诊断过程，避免 HTTP 超时

    事件流程：
    1. status: 状态更新（路由、检索进度）
    2. content: 文字内容（逐字推送）
    3. images: 图片信息（文字推送完毕后发送）
    4. result: 最终结构化结果
    5. done: 完成信号
    """
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")

    # 获取或创建会话
    session_id = body.session_id
    if session_id:
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在或已过期")
    else:
        session_id = session_manager.create_session()

    # 保存用户消息
    session_manager.add_message(session_id, "user", query)

    # 获取对话历史
    conversation_history = session_manager.get_conversation_history(session_id)
    graph_state = session_manager.get_graph_state(session_id)
    followup_count = graph_state.get("followup_count", 0) if graph_state else 0

    # 如果是追问回复，拼接上下文
    is_followup = bool(graph_state and graph_state.get("pending_followup"))
    full_query = query
    source = ""
    if is_followup:
        original_query = graph_state.get("original_query", "")
        followup_context = graph_state.get("followup_context", "")
        full_query = f"{original_query}\n专家追问：{followup_context}\n用户补充：{query}"
        session_manager.save_graph_state(session_id, {})
        # 追问时使用之前的品牌
        source = graph_state.get("source", "")

    logger.info("收到流式诊断请求", extra={"query": query, "session_id": session_id})

    # ========== 查询缓存（非追问场景） ==========
    cached = None
    if not is_followup:
        cached = query_cache.lookup(full_query)

    async def event_generator():
        """SSE 事件生成器"""
        nonlocal cached

        # ---- 缓存命中：回放缓存结果 ----
        if cached:
            logger.info("流式缓存命中", extra={"query": query[:60]})

            # content 事件：逐句推送以模拟流式
            cause_text = cached.get("cause_analysis", "")
            if cause_text:
                # 按句子切分，逐步 yield 实现打字机效果
                import re
                sentences = re.split(r'(?<=[。！？\n])\s*', cause_text)
                for sent in sentences:
                    if sent:
                        batch = sent + (" " if not sent.endswith("\n") else "")
                        yield {
                            "event": "content",
                            "data": json.dumps({"text": batch}, ensure_ascii=False),
                        }

            # images 事件
            cache_images = cached.get("images", [])
            cache_image_details = cached.get("image_details", [])
            image_urls = [
                f"{settings.STATIC_BASE_URL}/{img.lstrip('images/')}"
                if not img.startswith("http") else img
                for img in cache_images
            ]
            # 修正 image_details path
            for img_detail in cache_image_details:
                raw_path = img_detail.get("path", "") if isinstance(img_detail, dict) else img_detail.path
                if raw_path and not raw_path.startswith("http"):
                    if isinstance(img_detail, dict):
                        img_detail["path"] = f"{settings.STATIC_BASE_URL}/{raw_path.lstrip('images/')}"
                    else:
                        img_detail.path = f"{settings.STATIC_BASE_URL}/{raw_path.lstrip('images/')}"

            yield {
                "event": "images",
                "data": json.dumps({
                    "images": image_urls,
                    "image_details": cache_image_details,
                }, ensure_ascii=False),
            }

            # result 事件
            result_data = {
                "session_id": session_id,
                "summary": cached.get("summary", ""),
                "cause_analysis": cached.get("cause_analysis", ""),
                "solution_steps": cached.get("solution_steps", []),
                "references": cached.get("references", []),
                "iot_data": cached.get("iot_data"),
                "confidence": cached.get("confidence", 0.0),
                "router_decision": cached.get("router_decision", {}),
                "needs_followup": cached.get("needs_followup", False),
                "followup_question": cached.get("followup_question", ""),
            }
            yield {
                "event": "result",
                "data": json.dumps(result_data, ensure_ascii=False),
            }

            # done 事件
            done_data = {}
            if cached.get("needs_followup"):
                done_data = {
                    "needs_followup": True,
                    "followup_question": cached.get("followup_question", ""),
                }
            yield {
                "event": "done",
                "data": json.dumps(done_data, ensure_ascii=False),
            }

            # 保存助手回复到会话
            if cached.get("summary"):
                session_manager.add_message(session_id, "assistant", cached.get("summary", ""))
            return

        # ---- 缓存未命中：正常流式 ----
        captured_text = ""
        captured_result = {}
        captured_images = []
        captured_image_details = []
        is_done = False

        for event in stream_diagnosis(
            query=full_query,
            source=source,
            conversation_history=conversation_history,
            followup_count=followup_count,
        ):
            event_type = event.get("event", "message")
            event_data = event.get("data", {})

            # 收集文字内容
            if event_type == "content":
                captured_text += event_data.get("text", "")

            # 收集结果数据
            elif event_type == "result":
                captured_result = event_data
                # 注入 session_id
                event_data["session_id"] = session_id

            # 收集图片数据
            elif event_type == "images":
                captured_images = event_data.get("images", [])
                captured_image_details = event_data.get("image_details", [])

            # 收集 done 事件中的数据
            elif event_type == "done":
                is_done = True
                if event_data.get("needs_followup"):
                    captured_result = event_data

            # 返回 SSE 事件
            yield {
                "event": event_type,
                "data": json.dumps(event_data, ensure_ascii=False),
            }

        # 保存助手回复
        if captured_text:
            session_manager.add_message(session_id, "assistant", captured_text[:500])

        # 如果有追问，保存追问状态
        if captured_result.get("needs_followup"):
            session_manager.save_graph_state(session_id, {
                "pending_followup": True,
                "original_query": query,
                "followup_context": captured_result.get("followup_question", ""),
                "followup_count": followup_count + 1,
                "source": captured_result.get("router_decision", {}).get("source", ""),
            })
            return

        # ========== 存储缓存（非追问 + 非闲聊 + 有实质内容） ==========
        if not is_followup and captured_text and is_done:
            try:
                router = captured_result.get("router_decision", {})
                if router.get("intent") != "chitchat":
                    query_cache.store(full_query, {
                        "query": query,
                        "summary": captured_result.get("summary", captured_text[:200]),
                        "cause_analysis": captured_text,
                        "solution_steps": captured_result.get("solution_steps", []),
                        "references": captured_result.get("references", []),
                        "images": captured_result.get("images", captured_images),
                        "image_details": captured_result.get("image_details", captured_image_details),
                        "iot_data": captured_result.get("iot_data"),
                        "confidence": captured_result.get("confidence", 0.0),
                        "has_hallucination": False,
                        "router_decision": router,
                        "needs_followup": False,
                        "followup_question": "",
                    })
            except Exception:
                logger.warning("流式缓存存储失败", exc_info=True)

    return EventSourceResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.get("/api/session/{session_id}/history")
async def get_session_history(session_id: str):
    """获取会话对话历史"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return {"session_id": session_id, "messages": session.get("messages", [])}


@router.post("/api/ingest")
@limiter.limit(settings.RATE_LIMIT_INGEST)
async def ingest_data(request: Request, body: IngestRequest):
    """数据导入"""
    from ingest import run_ingest

    try:
        result = run_ingest(source=body.source, force_rebuild=body.force_rebuild)
        return {"status": "success", "detail": result}
    except Exception as e:
        logger.error("数据导入失败", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    health = HealthResponse(status="ok")

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        client.get_collections()
        health.qdrant_connected = True
    except Exception as e:
        logger.debug("Qdrant 连接检查失败", extra={"error": str(e)})

    try:
        from rag.index import get_index

        # 检查至少一个品牌的索引是否可加载
        for source_key in settings.SOURCE_FILES:
            try:
                get_index(source_key)
                health.index_loaded = True
                break
            except Exception as e:
                logger.debug("索引加载失败", extra={"source": source_key, "error": str(e)})
                continue
    except Exception as e:
        logger.debug("索引检查异常", extra={"error": str(e)})

    return health


@router.get("/api/cache/stats")
async def cache_stats():
    """查询缓存命中率统计"""
    stats = query_cache.stats
    return {
        "hits": stats["hits"],
        "misses": stats["misses"],
        "hit_rate": stats["hit_rate"],
        "entry_count": stats["entry_count"],
        "threshold": settings.CACHE_SIMILARITY_THRESHOLD,
        "ttl_seconds": settings.CACHE_TTL,
    }


@router.post("/api/cache/clear")
async def cache_clear():
    """清空查询缓存"""
    query_cache.clear()
    return {"status": "ok", "message": "缓存已清空"}
