"""
LangGraph 节点函数
每个节点负责一个独立的处理步骤
"""

import json
import logging
import re

from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agents.state import AgentState
from agents.tools import search_knowledge_base, get_iot_data, get_maintenance_history, get_last_kb_results
from config.settings import settings
from pathlib import Path
from models.schemas import ImageInfo

logger = logging.getLogger(__name__)


def _get_llm(max_tokens: int | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
        request_timeout=45.0,  # 单次 LLM 调用最长等 45 秒
    )


@retry(
    stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    before_sleep=lambda retry_state: logger.warning(
        "LLM 调用失败，正在重试",
        extra={"attempt": retry_state.attempt_number, "error": str(retry_state.outcome.exception())},
    ),
)
def _invoke_with_retry(llm, messages):
    """带重试的 LLM 调用"""
    return llm.invoke(messages)


def _build_memory_context(conversation_history: list[dict], max_turns: int = 5) -> str:
    """将最近 N 轮对话格式化为记忆文本，注入 agent prompt"""
    if not conversation_history:
        return ""

    recent = conversation_history[-max_turns * 2:]  # 每轮有 user + assistant 两条
    lines = []
    for msg in recent:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = msg.get("content", "").strip()
        if content:
            lines.append(f"[{role}] {content}")

    if not lines:
        return ""

    return "\n## 对话历史\n" + "\n".join(lines)


def _check_needs_followup(analysis: str, followup_count: int) -> tuple[bool, str]:
    """快速启发式追问判断（替代一次 LLM 调用，省 10-15 秒）

    基于分析文本中的不确定性关键词来判断是否需要追问。
    只在第 0 轮追问时触发。
    """
    if followup_count >= 1:
        return False, ""

    # 高不确定性关键词（出现任一个即追问）
    high_uncertainty = ["无法确定", "信息不足", "缺乏关键信息", "需要更多信息", "请提供"]
    # 中不确定性关键词（出现 2+ 个才追问）
    mid_uncertainty = ["可能", "不确定", "或者", "多种可能", "难以判断", "需确认"]

    analysis_lower = analysis.lower()

    for kw in high_uncertainty:
        if kw in analysis:
            return True, "请提供更多故障细节以帮助精确诊断。"

    mid_count = sum(1 for kw in mid_uncertainty if kw in analysis_lower)
    if mid_count >= 2:
        return True, "请提供更多故障细节以帮助精确诊断。"

    return False, ""



def _image_to_base64(img_path: str) -> str:
    """将本地图片转换为 base64 Data URL"""
    import base64

    # 处理路径：如果已有 images/ 前缀则去掉，避免重复
    clean_path = img_path.replace("images/", "").replace("images\\", "")
    full_path = settings.IMAGES_DIR / clean_path
    if not full_path.exists():
        logger.warning(f"图片不存在: {full_path}")
        return ""

    with open(full_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode("utf-8")

    ext = Path(img_path).suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/jpeg")

    return f"data:{mime_type};base64,{img_data}"


def _filter_images_by_llm_response(full_response: str, images: list[str]) -> list[str]:
    """从 LLM 回复中解析引用的图片编号，过滤出有用图片。
    LLM 回复中用 [图片X] 标记引用的图片，未引用的图片不发送到前端。
    """
    refs = set(re.findall(r"\[图片(\d+)\]", full_response))
    if not refs:
        return []  # LLM 没引用任何图片 → 不发
    filtered = []
    for n in sorted(refs, key=int):
        idx = int(n) - 1
        if 0 <= idx < len(images):
            filtered.append(images[idx])
    return filtered


def _build_multimodal_messages(
    system_prompt: str,
    query: str,
    kb_result: str,
    memory_context: str,
    images: list[str],
    extra_context: str = "",
) -> list:
    """
    构建多模态消息，将图片传给 LLM
    只有当 LLM 支持视觉（如 gpt-4o）时才生效
    """
    if not images:
        # 无图片时返回纯文本消息
        human_content = f"用户问题：{query}\n\n知识库检索结果：\n{kb_result}"
        if extra_context:
            human_content += f"\n\n{extra_context}"
        human_content += memory_context
        return [("system", system_prompt), ("human", human_content)]

# 有多��图片时构建多模态消息
    content_parts = []

    # 文本部分
    text_content = f"用户问题：{query}\n\n知识库检索结果：\n{kb_result}"
    if extra_context:
        text_content += f"\n\n{extra_context}"
    text_content += memory_context
    text_content += "\n\n以下是相关的参考图片，请结合图片分析：\n"
    for i, img_path in enumerate(images, 1):
        text_content += f"[图片{i}] {img_path}\n"
    text_content += "请在回复中用 [图片X] 标记你实际参考了的图片，没有参考的不要标记。"
    content_parts.append({"type": "text", "text": text_content})

    # 图片部分
    for img_path in images:
        # 构建本地文件 URL
        img_url = _image_to_base64(img_path)
        if img_url:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": img_url},
            })

    return [("system", system_prompt), ("human", content_parts)]


# ==================== 路由节点 ====================

def router_node(state: AgentState) -> dict:
    """中控路由：品牌识别 + 故障分类（分诊专家模式）"""
    query = state["query"].strip()

    # ---- 闲聊前置拦截（省一次 LLM 调用） ----
    chitchat_keywords = ["你好", "您好", "嗨", "哈喽", "hello", "hi", "谢谢", "感谢", "再见", "拜拜"]
    if len(query) < 8 and any(kw in query.lower() for kw in chitchat_keywords):
        logger.info(f"[路由] 闲聊拦截: {query}")
        return {
            "intent": "chitchat",
            "fault_type": "unknown",
            "target_agent": "cnc_expert",
            "source": "unknown",
            "router_reasoning": "短文本命中闲聊关键词",
            "needs_followup": False,
            "followup_question": "",
        }

    llm = _get_llm()

    system_prompt = """你是一个资深的工业数控机床（FANUC/SIEMENS）分诊专家。你的任务是分析用户的故障描述，提取机床品牌，并将其路由到正确的专家处理通道。

【第一维：品牌识别规则（Brand Extraction）】
请判断用户提问属于哪个机床品牌：
1. "FANUC"：用户明确提及（发那科、FANUC），或者提问中包含发那科特征代码（如 SV、PS 开头的报警码，或 PMC、JD1A 等特征词）。
2. "SIEMENS"：用户明确提及（西门子、SIEMENS、840D），或者包含西门子特征代码（如 F 开头的故障码）。
3. "UNKNOWN"：如果提问是纯物理现象（如"主轴异响"、"导轨卡死"），且完全没有提及品牌，必须输出 UNKNOWN！

【第二维：故障分类规则（Fault Classification）】
请将提问分类为以下 4 种类型之一：
1. "ELECTRICAL_FAULT"（电气/系统故障）：涉及报警码、参数、伺服、电路等。
2. "MECHANICAL_FAULT"（机械/液压故障）：涉及异响、震动、发热、漏油、卡涩等纯物理现象。
3. "COMPOUND_FAULT"（复合故障）：同时包含机械物理现象与电气报警代码。
4. "UNCLEAR"（模糊提问）：提问极其简短，无法判断软硬件故障。

【输出要求】
绝对不要回答用户的具体问题！必须且只能返回一个合法的 JSON 对象，格式如下：
{
    "brand": "FANUC 或 SIEMENS 或 UNKNOWN",
    "route_to": "填入上述4种故障类型之一",
    "reason": "说明你的分类与品牌判定理由（限30字以内）"
}"""

    memory_context = _build_memory_context(state.get("conversation_history", []))

    response = _invoke_with_retry(llm, [
        ("system", system_prompt),
        ("human", f"用户输入：{state['query']}{memory_context}"),
    ])

    try:
        data = json.loads(response.content)
    except json.JSONDecodeError:
        data = {
            "brand": "UNKNOWN",
            "route_to": "UNCLEAR",
            "reason": "路由解析失败，需要追问品牌",
        }

    # 解析新格式字段
    brand = data.get("brand", "UNKNOWN").upper()
    route_to = data.get("route_to", "UNCLEAR").upper()
    reason = data.get("reason", "")

    # ---- 映射到下游 state 字段（保持兼容） ----

    # brand → source（小写，供知识库检索用）
    brand_source_map = {"FANUC": "fanuc", "SIEMENS": "siemens", "UNKNOWN": "unknown"}
    source = brand_source_map.get(brand, "unknown")

    # brand == UNKNOWN → 追问品牌
    needs_followup = brand == "UNKNOWN"
    followup_question = "请告诉我您的设备是什么品牌？（如 FANUC、Siemens 等）" if needs_followup else ""

    # route_to → fault_type + target_agent
    # ELECTRICAL_FAULT → cnc_expert（纯电气）
    # MECHANICAL_FAULT → machine_expert（纯机械）
    # COMPOUND_FAULT → compound_expert（双专家都走）
    # UNCLEAR → 追问用户补充信息
    if route_to == "UNCLEAR":
        needs_followup = True
        followup_question = "您的描述较简短，请补充故障详情：是否有报警代码？是电气异常还是机械异响？"
        fault_type = "unknown"
        target_agent = "cnc_expert"  # 占位，不会实际执行
    elif route_to == "COMPOUND_FAULT":
        fault_type = "compound_fault"
        target_agent = "compound_expert"
    else:
        route_map = {
            "ELECTRICAL_FAULT": ("cnc_fault", "cnc_expert"),
            "MECHANICAL_FAULT": ("mechanical_fault", "machine_expert"),
        }
        fault_type, target_agent = route_map.get(route_to, ("cnc_fault", "cnc_expert"))

    logger.info(f"[路由] brand={brand}, route_to={route_to}, source={source}, needs_followup={needs_followup}")
    return {
        "intent": "fault_diagnosis",
        "fault_type": fault_type,
        "target_agent": target_agent,
        "source": source,
        "router_reasoning": reason,
        "needs_followup": needs_followup,
        "followup_question": followup_question,
    }


# ==================== CNC 专家节点 ====================

def cnc_expert_node(state: AgentState) -> dict:
    """CNC 维修专家：检索知识库 + IoT 数据 → 诊断分析"""
    llm = _get_llm()
    llm_with_tools = llm.bind_tools([search_knowledge_base, get_iot_data, get_maintenance_history])

    # 直接使用 Router 传来的品牌
    query = state["query"]
    source = state.get("source", "fanuc")  # Router 已判断品牌
    if source == "unknown":
        source = "fanuc"  # 兜底默认

    # 检索知识库
    kb_result = search_knowledge_base.invoke({"query": query, "source": source})

    # 构建记忆上下文
    memory_context = _build_memory_context(state.get("conversation_history", []))

    # 收集检索结果中的图片（images + parent_images）
    kb_results = get_last_kb_results()
    all_images = []
    for r in kb_results:
        all_images.extend(r.get("images", []))
        all_images.extend(r.get("parent_images", []))
    # 去重并限制数量
    unique_images = list(dict.fromkeys(all_images))[:5]

    # 调用 LLM（可触发 IoT function calling）
    system_prompt = """你是 CNC 数控系统维修专家，精通 FANUC 和 Siemens 840D。
根据检索到的故障手册内容、历史维修记录和 IoT 实时数据，为用户提供专业诊断分析。
要求：
1. 引用具体出处（如"根据手册 SV0410..."）
2. 如果需要查看机床实时数据来辅助诊断，调用 get_iot_data 函数
3. 如果需要参考同类故障的历史维修经验，调用 get_maintenance_history 函数
4. 给出可操作的排除步骤
5. 如果提供了图片，请结合图片中的结构图/解剖图进行分析说明"""

    # 构建多模态消息
    messages = _build_multimodal_messages(
        system_prompt=system_prompt,
        query=query,
        kb_result=kb_result,
        memory_context=memory_context,
        images=unique_images,
    )

    response = _invoke_with_retry(llm_with_tools, messages)

    # 处理可能的 tool call（IoT / 历史维修记录）
    iot_data = None
    maintenance_data = None
    analysis = response.content

    if response.tool_calls:
        tool_results = []
        for tool_call in response.tool_calls:
            if tool_call["name"] == "get_iot_data":
                iot_result = get_iot_data.invoke(tool_call["args"])
                iot_data = json.loads(iot_result)
                tool_results.append(f"IoT实时数据：\n{iot_result}")
            elif tool_call["name"] == "get_maintenance_history":
                maint_result = get_maintenance_history.invoke(tool_call["args"])
                maintenance_data = maint_result
                tool_results.append(f"历史维修记录：\n{maint_result}")

        # 让 LLM 结合所有工具结果再分析一次（多模态）
        if tool_results:
            extra_context = "\n\n".join(tool_results)
            follow_messages = _build_multimodal_messages(
                system_prompt=system_prompt,
                query=query,
                kb_result=kb_result,
                memory_context=memory_context,
                images=unique_images,
                extra_context=extra_context,
            )
            follow_up = _invoke_with_retry(llm, follow_messages)
            analysis = follow_up.content

    # 从检索结果构建丰富的溯源引用
    references = []
    seen = set()
    for r in kb_results:
        if r["chunk_id"] not in seen:
            seen.add(r["chunk_id"])
            references.append({
                "chunk_id": r["chunk_id"],
                "source": r["source"],
                "section_title": r["section_title"],
                "alarm_code": r["alarm_code"],
                "text_snippet": r["text"][:150],
                "score": r["score"],
                "images": r["images"],
                "verified": False,
            })

    # LLM 过滤：只保留 LLM 实际引用的图片
    filtered_images = _filter_images_by_llm_response(analysis, unique_images)

    # 构建结构化图片信息
    image_details = []
    for img_path in filtered_images:
        img_description = ""
        for r in kb_results:
            if img_path in r.get("images", []) or img_path in r.get("parent_images", []):
                img_description = r.get("section_title", "")
                break
        image_details.append(ImageInfo(
            path=img_path,
            alt=img_path.split("/")[-1].split(".")[0] if img_path else "",
            description=img_description,
        ))

    logger.info(f"[cnc_expert] images={unique_images}, filtered={filtered_images}, image_details={len(image_details)}")
    return {
        "expert_analysis": analysis,
        "expert_source": source,
        "expert_confidence": 0.7,
        "retrieval_results": [{"source": source, "text": kb_result[:200]}],
        "iot_data": iot_data,
        "references": references,
        "images": filtered_images,
        "image_details": image_details,
        "needs_followup": False,
        "followup_question": "",
        "followup_count": state.get("followup_count", 0),
    }


# ==================== 机床专家节点 ====================

def machine_expert_node(state: AgentState) -> dict:
    """机床维修专家：检索知识库（根据 Router 品牌判断）+ IoT → 诊断分析"""
    llm = _get_llm()
    llm_with_tools = llm.bind_tools([search_knowledge_base, get_iot_data, get_maintenance_history])

    query = state["query"]

    # 使用 Router 判断的品牌，兜底默认 vmc850
    source = state.get("source", "vmc850")
    if source == "unknown":
        source = "vmc850"  # 机械故障兜底默认

    # 检索对应品牌的知识库
    kb_result = search_knowledge_base.invoke({"query": query, "source": source})

    # 构建记忆上下文
    memory_context = _build_memory_context(state.get("conversation_history", []))

    # 品牌显示名称映射
    brand_display = {"fanuc": "FANUC", "siemens": "Siemens 840D", "vmc850": "VMC850"}

    # 收集检索结果中的图片（images + parent_images）
    kb_results = get_last_kb_results()
    all_images = []
    for r in kb_results:
        all_images.extend(r.get("images", []))
        all_images.extend(r.get("parent_images", []))
    unique_images = list(dict.fromkeys(all_images))[:5]

    # 调用 LLM（可触发 IoT）
    system_prompt = f"""你是 {brand_display.get(source, source.upper())} 立式加工中心机械维修专家。
根据检索到的维修手册内容、历史维修记录和 IoT 实时数据，为用户提供专业诊断分析。
要求：
1. 引用具体出处（如"根据 {brand_display.get(source, source.upper())} 手册..."）
2. 如果需要查看机床实时数据来辅助诊断，调用 get_iot_data 函数
3. 如果需要参考同类故障的历史维修经验，调用 get_maintenance_history 函数
4. 排除步骤要具体可操作，包含安全提醒
5. 如果提供了图片，请结合图片中的结构图/解剖图进行分析说明"""

    # 构建多模态消息
    messages = _build_multimodal_messages(
        system_prompt=system_prompt,
        query=query,
        kb_result=kb_result,
        memory_context=memory_context,
        images=unique_images,
    )

    response = _invoke_with_retry(llm_with_tools, messages)

    iot_data = None
    maintenance_data = None
    analysis = response.content

    if response.tool_calls:
        tool_results = []
        for tool_call in response.tool_calls:
            if tool_call["name"] == "get_iot_data":
                iot_result = get_iot_data.invoke(tool_call["args"])
                iot_data = json.loads(iot_result)
                tool_results.append(f"IoT实时数据：\n{iot_result}")
            elif tool_call["name"] == "get_maintenance_history":
                maint_result = get_maintenance_history.invoke(tool_call["args"])
                maintenance_data = maint_result
                tool_results.append(f"历史维修记录：\n{maint_result}")

        # 让 LLM 结合所有工具结果再分析一次（多模态）
        if tool_results:
            extra_context = "\n\n".join(tool_results)
            follow_messages = _build_multimodal_messages(
                system_prompt=system_prompt,
                query=query,
                kb_result=kb_result,
                memory_context=memory_context,
                images=unique_images,
                extra_context=extra_context,
            )
            follow_up = _invoke_with_retry(llm, follow_messages)
            analysis = follow_up.content

    # 从检索结果构建丰富的溯源引用
    references = []
    seen = set()
    for r in kb_results:
        if r["chunk_id"] not in seen:
            seen.add(r["chunk_id"])
            references.append({
                "chunk_id": r["chunk_id"],
                "source": r["source"],
                "section_title": r["section_title"],
                "alarm_code": r["alarm_code"],
                "text_snippet": r["text"][:150],
                "score": r["score"],
                "images": r["images"],
                "verified": False,
            })

    # LLM 过滤：只保留 LLM 实际引用的图片
    filtered_images = _filter_images_by_llm_response(analysis, unique_images)

    # 构建结构化图片信息
    image_details = []
    for img_path in filtered_images:
        img_description = ""
        for r in kb_results:
            if img_path in r.get("images", []):
                img_description = r.get("section_title", "")
                break
        image_details.append(ImageInfo(
            path=img_path,
            alt=img_path.split("/")[-1].split(".")[0] if img_path else "",
            description=img_description,
        ))

    return {
        "expert_analysis": analysis,
        "expert_source": source,
        "expert_confidence": 0.7,
        "retrieval_results": [{"source": source, "text": kb_result[:200]}],
        "iot_data": iot_data,
        "references": references,
        "images": filtered_images,
        "image_details": image_details,
        "needs_followup": False,
        "followup_question": "",
        "followup_count": state.get("followup_count", 0),
    }


# ==================== 复合专家节点 ====================

def compound_expert_node(state: AgentState) -> dict:
    """复合故障专家：CNC 专家 + 机械专家顺序执行，合并结果"""
    llm = _get_llm()
    llm_with_tools = llm.bind_tools([search_knowledge_base, get_iot_data, get_maintenance_history])

    query = state["query"]
    brand = state.get("source", "fanuc")  # Router 判断的品牌（fanuc / siemens）
    if brand == "unknown":
        brand = "fanuc"

    memory_context = _build_memory_context(state.get("conversation_history", []))

    # ---- CNC 专家：用品牌检索数控知识库 ----
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

    cnc_response = _invoke_with_retry(llm_with_tools, cnc_messages)
    cnc_analysis = cnc_response.content

    # 处理 CNC 工具调用
    iot_data = None
    if cnc_response.tool_calls:
        tool_results = []
        for tool_call in cnc_response.tool_calls:
            if tool_call["name"] == "get_iot_data":
                iot_result = get_iot_data.invoke(tool_call["args"])
                iot_data = json.loads(iot_result)
                tool_results.append(f"IoT实时数据：\n{iot_result}")
            elif tool_call["name"] == "get_maintenance_history":
                maint_result = get_maintenance_history.invoke(tool_call["args"])
                tool_results.append(f"历史维修记录：\n{maint_result}")

        if tool_results:
            extra_context = "\n\n".join(tool_results)
            cnc_messages = _build_multimodal_messages(
                system_prompt=cnc_system_prompt,
                query=query,
                kb_result=kb_result_cnc,
                memory_context=memory_context,
                images=cnc_images,
                extra_context=extra_context,
            )
            cnc_analysis = _invoke_with_retry(llm, cnc_messages).content

    # ---- 机械专家：固定用 vmc850 检索机械知识库 ----
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

    mech_analysis = _invoke_with_retry(llm, mech_messages).content

    # ---- 合并结果 ----
    combined_analysis = f"## 电气/系统层面（{brand.upper()}）\n\n{cnc_analysis}\n\n---\n\n## 机械/液压层面（VMC850）\n\n{mech_analysis}"

    # 合并引用
    all_references = []
    seen = set()
    for r in kb_results_cnc + kb_results_mech:
        if r["chunk_id"] not in seen:
            seen.add(r["chunk_id"])
            all_references.append({
                "chunk_id": r["chunk_id"],
                "source": r["source"],
                "section_title": r["section_title"],
                "alarm_code": r["alarm_code"],
                "text_snippet": r["text"][:150],
                "score": r["score"],
                "images": r["images"],
                "verified": False,
            })

    # LLM 过滤：分别从各自回复中过滤图片，再合并
    filtered_cnc = _filter_images_by_llm_response(cnc_analysis, cnc_images)
    filtered_mech = _filter_images_by_llm_response(mech_analysis, mech_images)
    all_images = list(dict.fromkeys(filtered_cnc + filtered_mech))[:5]

    image_details = []
    all_kb_results = kb_results_cnc + kb_results_mech
    for img_path in all_images:
        img_description = ""
        for r in all_kb_results:
            if img_path in r.get("images", []) or img_path in r.get("parent_images", []):
                img_description = r.get("section_title", "")
                break
        image_details.append(ImageInfo(
            path=img_path,
            alt=img_path.split("/")[-1].split(".")[0] if img_path else "",
            description=img_description,
        ))

    logger.info(f"[compound_expert] cnc_images={len(cnc_images)}, mech_images={len(mech_images)}, total_refs={len(all_references)}")
    return {
        "expert_analysis": combined_analysis,
        "expert_source": brand,
        "expert_confidence": 0.7,
        "retrieval_results": [
            {"source": brand, "text": kb_result_cnc[:200]},
            {"source": "vmc850", "text": kb_result_mech[:200]},
        ],
        "iot_data": iot_data,
        "references": all_references,
        "images": all_images,
        "image_details": image_details,
        "needs_followup": False,
        "followup_question": "",
        "followup_count": state.get("followup_count", 0),
    }


# ==================== 报告节点 ====================

def report_node(state: AgentState) -> dict:
    """报告节点：从专家分析文本中提取结构化报告（纯解析，不调 LLM）"""
    import re

    analysis = state.get("expert_analysis", "")

    # 尝试从分析中提取已有结构
    summary = ""
    cause_analysis = analysis
    solution_steps = []

    # 按常见格式分割：摘要/原因/方案
    # 匹配 "问题摘要" "原因分析" "解决方案" 等标题
    sections = re.split(r'\n(?=#{1,3}\s|(?:问题|故障|原因|解决|排除|处理|方案|步骤|措施))', analysis, maxsplit=1)

    if len(sections) > 1:
        summary = sections[0].strip()[:200]
        cause_analysis = sections[1].strip()
    else:
        # 取前200字作为摘要
        summary = analysis[:200]

    # 提取编号步骤（1. / 1、/ 步骤1 / ① 等格式）
    step_pattern = re.findall(
        r'(?:^|\n)\s*(?:\d+[\.\)、]\s*|步骤\s*\d+[：:]?\s*|[①②③④⑤⑥⑦⑧])+\s*(.+?)(?=\n\s*(?:\d+[\.\)、]|步骤\s*\d+[：:]?|[①②③④⑤⑥⑦⑧])|$)',
        cause_analysis, re.MULTILINE
    )
    if step_pattern:
        solution_steps = [s.strip() for s in step_pattern if s.strip()]

    # 如果没提取到步骤，按句子分割
    if not solution_steps:
        lines = [l.strip() for l in cause_analysis.split('\n') if l.strip() and len(l.strip()) > 10]
        solution_steps = lines[:8]  # 最多8条

    return {
        "summary": summary,
        "cause_analysis": cause_analysis,
        "solution_steps": solution_steps,
        # 保留专家节点返回的图片，不覆盖
        "images": state.get("images", []),
        "image_details": state.get("image_details", []),
    }
