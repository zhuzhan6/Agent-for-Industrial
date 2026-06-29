"""
流式诊断模块
使用 SSE（Server-Sent Events）逐步返回诊断结果

标准流程：
1. 文字内容通过 content 事件逐字推送
2. 文字推送完毕后，发送 images 事件携带图片 URL 和图注
3. 最后发送 done 事件表示完成
"""

import json
import logging
from typing import Generator, Dict, Any

from langchain_openai import ChatOpenAI

from agents.state import AgentState
from agents.tools import search_knowledge_base, get_iot_data, get_maintenance_history, get_last_kb_results
from agents.nodes import (
    router_node,
    _get_llm,
    _build_memory_context,
    _build_multimodal_messages,
    _filter_images_by_llm_response,
)
from config.settings import settings

logger = logging.getLogger(__name__)


def _sse_event(event: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建 SSE 事件字典
    返回格式：{"event": "xxx", "data": {...}}
    由 EventSourceResponse 处理序列化
    """
    return {"event": event, "data": data}


def _stream_compound(
    query: str,
    brand: str,
    conversation_history: list[dict],
    followup_count: int,
    fault_type: str,
    target_agent: str,
    router_reasoning: str,
) -> Generator[Dict[str, Any], None, None]:
    """复合故障流式诊断：CNC 专家 + 机械专家顺序执行"""
    from agents.nodes import _get_llm, _build_memory_context, _build_multimodal_messages, _check_needs_followup
    from agents.tools import search_knowledge_base, get_iot_data, get_maintenance_history, get_last_kb_results
    from models.schemas import ImageInfo

    llm = _get_llm()
    memory_context = _build_memory_context(conversation_history)

    # ========== CNC 专家 ==========
    yield _sse_event("status", {"step": "cnc_diagnosis", "message": f"正在分析 {brand.upper()} 电气/系统层面..."})

    kb_result_cnc = search_knowledge_base.invoke({"query": query, "source": brand})
    kb_results_cnc = get_last_kb_results()

    cnc_images = []
    for r in kb_results_cnc:
        cnc_images.extend(r.get("images", []))
        cnc_images.extend(r.get("parent_images", []))
    cnc_images = list(dict.fromkeys(cnc_images))[:3]

    cnc_system_prompt = f"""你是 CNC 数控系统维修专家，精通 {brand.upper()} 系统。
用户报告了一个复合故障（同时包含电气报警和机械现象）。
请专注于电气/系统层面的分析：报警码含义、参数异常、伺服/PLC 诊断。
要求：引用具体出处，给出可操作的排查步骤。"""

    cnc_messages = _build_multimodal_messages(
        system_prompt=cnc_system_prompt,
        query=query,
        kb_result=kb_result_cnc,
        memory_context=memory_context,
        images=cnc_images,
    )

    cnc_response = ""
    try:
        for chunk in llm.stream(cnc_messages):
            if chunk.content:
                cnc_response += chunk.content
                yield _sse_event("content", {"text": chunk.content})
    except Exception as e:
        logger.error(f"CNC 专家流式调用失败: {e}")
        yield _sse_event("error", {"message": f"CNC 诊断失败: {str(e)}"})
        return

    # ========== 分隔线 ==========
    yield _sse_event("content", {"text": "\n\n---\n\n## 机械/液压层面（VMC850）\n\n"})

    # ========== 机械专家 ==========
    yield _sse_event("status", {"step": "mech_diagnosis", "message": "正在分析机械/液压层面..."})

    kb_result_mech = search_knowledge_base.invoke({"query": query, "source": "vmc850"})
    kb_results_mech = get_last_kb_results()

    mech_images = []
    for r in kb_results_mech:
        mech_images.extend(r.get("images", []))
        mech_images.extend(r.get("parent_images", []))
    mech_images = list(dict.fromkeys(mech_images))[:3]

    mech_system_prompt = """你是 VMC850 立式加工中心机械维修专家。
用户报告了一个复合故障（同时包含电气报警和机械现象）。
请专注于机械/液压层面的分析：主轴、导轨、刀库、轴承、冷却、气动等。
要求：引用具体出处，给出可操作的排查步骤和安全提醒。"""

    mech_messages = _build_multimodal_messages(
        system_prompt=mech_system_prompt,
        query=query,
        kb_result=kb_result_mech,
        memory_context=memory_context,
        images=mech_images,
    )

    mech_response = ""
    try:
        for chunk in llm.stream(mech_messages):
            if chunk.content:
                mech_response += chunk.content
                yield _sse_event("content", {"text": chunk.content})
    except Exception as e:
        logger.error(f"机械专家流式调用失败: {e}")
        yield _sse_event("error", {"message": f"机械诊断失败: {str(e)}"})
        return

    # ========== 图片 ==========
    # LLM 过滤：分别从各自回复中过滤图片，再合并
    filtered_cnc = _filter_images_by_llm_response(cnc_response, cnc_images)
    filtered_mech = _filter_images_by_llm_response(mech_response, mech_images)
    all_images = list(dict.fromkeys(filtered_cnc + filtered_mech))[:5]
    all_kb = kb_results_cnc + kb_results_mech
    image_details = []
    for img_path in all_images:
        img_desc = ""
        for r in all_kb:
            if img_path in r.get("images", []) or img_path in r.get("parent_images", []):
                img_desc = r.get("section_title", "")
                break
        image_details.append({
            "path": f"{settings.STATIC_BASE_URL}/{img_path.lstrip('images/')}" if not img_path.startswith("http") else img_path,
            "alt": img_path.split("/")[-1].split(".")[0] if img_path else "",
            "description": img_desc,
        })
    image_urls = [
        f"{settings.STATIC_BASE_URL}/{img.lstrip('images/')}" if not img.startswith("http") else img
        for img in all_images
    ]
    yield _sse_event("images", {"images": image_urls, "image_details": image_details})

    # ========== 最终结果 ==========
    full_response = cnc_response + "\n\n" + mech_response
    references = []
    seen = set()
    for r in all_kb:
        if r.get("chunk_id") not in seen:
            seen.add(r.get("chunk_id"))
            references.append({
                "chunk_id": r.get("chunk_id", ""),
                "source": r.get("source", ""),
                "section_title": r.get("section_title", ""),
                "alarm_code": r.get("alarm_code", ""),
                "text_snippet": r.get("text", "")[:150],
                "score": r.get("score", 0),
            })

    solution_steps = []
    for line in full_response.split("\n"):
        line = line.strip()
        if line and (line[0].isdigit() or line.startswith("-") or line.startswith("•")):
            solution_steps.append(line)

    yield _sse_event("result", {
        "summary": full_response[:200],
        "cause_analysis": full_response,
        "solution_steps": solution_steps[:10],
        "references": references,
        "iot_data": None,
        "confidence": 0.7,
        "router_decision": {
            "intent": "fault_diagnosis",
            "fault_type": "compound_fault",
            "target_agent": "compound_expert",
            "reasoning": router_reasoning,
        },
    })

    yield _sse_event("done", {})


def stream_diagnosis(
    query: str,
    source: str = "",
    conversation_history: list[dict] = None,
    followup_count: int = 0,
) -> Generator[Dict[str, Any], None, None]:
    """
    流式诊断生成器
    逐步 yield SSE 事件字典

    事件类型：
    - status: 状态更新（路由、检索、诊断进度）
    - content: 文字内容（逐字推送）
    - images: 图片信息（文字推送完毕后发送）
    - result: 最终结构化结果
    - done: 完成信号
    - error: 错误信息
    """
    conversation_history = conversation_history or []

    # ========== 1. 路由 ==========
    yield _sse_event("status", {"step": "routing", "message": "正在分析意图..."})

    # 如果没有指定品牌，调用路由
    if not source:
        router_state: AgentState = {
            "query": query,
            "intent": "",
            "fault_type": "",
            "target_agent": "",
            "source": "",
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
        router_result = router_node(router_state)
        source = router_result.get("source", "fanuc")
        intent = router_result.get("intent", "fault_diagnosis")
        needs_followup = router_result.get("needs_followup", False)
        followup_question = router_result.get("followup_question", "")
        fault_type = router_result.get("fault_type", "unknown")
        target_agent = router_result.get("target_agent", "cnc_expert")
        router_reasoning = router_result.get("router_reasoning", "")

        # 闲聊
        if intent == "chitchat":
            chitchat_reply = "你好！我是工业排障助手，请描述您遇到的设备故障或报警代码，我将为您智能诊断。"
            yield _sse_event("content", {"text": chitchat_reply})
            yield _sse_event("images", {"images": [], "image_details": []})
            yield _sse_event("done", {
                "intent": "chitchat",
                "needs_followup": False,
            })
            return

        # 需要追问
        if needs_followup:
            yield _sse_event("content", {"text": followup_question})
            yield _sse_event("images", {"images": [], "image_details": []})
            yield _sse_event("done", {
                "needs_followup": True,
                "followup_question": followup_question,
            })
            return

        yield _sse_event("status", {
            "step": "routing_done",
            "message": f"品牌: {source}, 故障类型: {fault_type}",
            "source": source,
            "fault_type": fault_type,
            "target_agent": target_agent,
        })
    else:
        # 已指定品牌
        fault_type = "cnc_fault" if source in ("fanuc", "siemens") else "mechanical_fault"
        target_agent = "cnc_expert" if fault_type == "cnc_fault" else "machine_expert"
        router_reasoning = ""

    # ========== 复合故障：双专家路径 ==========
    if target_agent == "compound_expert":
        yield from _stream_compound(query, source, conversation_history, followup_count, fault_type, target_agent, router_reasoning)
        return

    # ========== 2. 检索 ==========
    yield _sse_event("status", {"step": "retrieval", "message": "正在检索知识库..."})

    kb_result = search_knowledge_base.invoke({"query": query, "source": source})
    kb_results = get_last_kb_results()

    # 收集图片
    all_images = []
    for r in kb_results:
        all_images.extend(r.get("images", []))
        all_images.extend(r.get("parent_images", []))
    unique_images = list(dict.fromkeys(all_images))[:5]

    yield _sse_event("status", {
        "step": "retrieval_done",
        "message": f"检索到 {len(kb_results)} 条结果，{len(unique_images)} 张图片",
        "results_count": len(kb_results),
        "images_count": len(unique_images),
    })

    # ========== 3. LLM 流式诊断（文字部分） ==========
    yield _sse_event("status", {"step": "diagnosis", "message": "正在生成诊断..."})

    llm = _get_llm()
    memory_context = _build_memory_context(conversation_history)

    # 构建消息
    brand_display = {"fanuc": "FANUC", "siemens": "Siemens 840D", "vmc850": "VMC850"}
    system_prompt = f"""你是 {brand_display.get(source, source.upper())} 数控系统维修专家。
根据检索到的故障手册内容，为用户提供专业诊断分析。
要求：
1. 引用具体出处
2. 给出可操作的排除步骤
3. 如果提供了图片，请结合图片分析"""

    messages = _build_multimodal_messages(
        system_prompt=system_prompt,
        query=query,
        kb_result=kb_result,
        memory_context=memory_context,
        images=unique_images,
    )

    # 流式调用 LLM - 逐字推送文字
    full_response = ""
    try:
        for chunk in llm.stream(messages):
            if chunk.content:
                full_response += chunk.content
                yield _sse_event("content", {"text": chunk.content})
    except Exception as e:
        logger.error(f"LLM 流式调用失败: {e}")
        yield _sse_event("error", {"message": f"LLM 调用失败: {str(e)}"})
        return

    # ========== 4. 尝试调用工具 ==========
    iot_data = None
    if "SV" in query or "伺服" in query or "主轴" in query:
        try:
            iot_result = get_iot_data.invoke({"machine_id": f"{source.upper()}-001", "sensor_type": "all"})
            iot_data = json.loads(iot_result) if isinstance(iot_result, str) else iot_result
            yield _sse_event("status", {"step": "iot", "message": "已获取 IoT 实时数据"})
        except Exception as e:
            logger.warning(f"IoT 数据获取失败: {e}")

    # ========== 5. 文字推送完毕，发送图片信息 ==========
    # LLM 过滤：只保留 LLM 实际引用的图片
    filtered_images = _filter_images_by_llm_response(full_response, unique_images)

    # 构建图片详情
    image_details = []
    for img_path in filtered_images:
        img_description = ""
        for r in kb_results:
            if img_path in r.get("images", []) or img_path in r.get("parent_images", []):
                img_description = r.get("section_title", "")
                break
        image_details.append({
            "path": f"{settings.STATIC_BASE_URL}/{img_path.lstrip('images/')}" if not img_path.startswith("http") else img_path,
            "alt": img_path.split("/")[-1].split(".")[0] if img_path else "",
            "description": img_description,
        })

    # 图片 URL
    image_urls = [
        f"{settings.STATIC_BASE_URL}/{img.lstrip('images/')}" if not img.startswith("http") else img
        for img in filtered_images
    ]

    # 发送图片事件（文字推送完毕后）
    yield _sse_event("images", {
        "images": image_urls,
        "image_details": image_details,
    })

    # ========== 6. 构建并发送最终结果 ==========
    # 构建引用
    references = []
    seen = set()
    for r in kb_results:
        if r.get("chunk_id") not in seen:
            seen.add(r.get("chunk_id"))
            references.append({
                "chunk_id": r.get("chunk_id", ""),
                "source": r.get("source", ""),
                "section_title": r.get("section_title", ""),
                "alarm_code": r.get("alarm_code", ""),
                "text_snippet": r.get("text", "")[:150],
                "score": r.get("score", 0),
            })

    # 提取摘要和步骤
    summary = full_response[:200] if full_response else ""
    solution_steps = []
    for line in full_response.split("\n"):
        line = line.strip()
        if line and (line[0].isdigit() or line.startswith("-") or line.startswith("•")):
            solution_steps.append(line)

    # 发送最终结果
    yield _sse_event("result", {
        "summary": summary,
        "cause_analysis": full_response,
        "solution_steps": solution_steps[:10],
        "references": references,
        "iot_data": iot_data,
        "confidence": 0.7,
        "router_decision": {
            "intent": "fault_diagnosis",
            "fault_type": fault_type,
            "target_agent": target_agent,
            "reasoning": router_reasoning,
        },
    })

    # ========== 7. 完成 ==========
    yield _sse_event("done", {})
