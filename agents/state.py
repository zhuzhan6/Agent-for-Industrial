"""
LangGraph 状态定义
图中所有节点共享的状态结构
"""

from typing import Annotated, Any, TypedDict

from langgraph.graph import add_messages


class AgentState(TypedDict):
    """多智能体共享状态"""

    # 输入
    query: str

    # 路由决策
    intent: str  # "chitchat" | "fault_diagnosis"
    fault_type: str  # "cnc_fault" | "mechanical_fault" | "unknown"
    target_agent: str  # "cnc_expert" | "machine_expert"
    source: str  # "fanuc" | "siemens" | "vmc850" | ""（品牌，由 Router 判断）
    router_reasoning: str

    # 检索结果
    retrieval_results: list[dict]

    # IoT 数据
    iot_data: dict | None

    # 专家分析
    expert_analysis: str
    expert_source: str  # "fanuc" | "siemens" | "vmc850"
    expert_confidence: float

    # 追问
    needs_followup: bool
    followup_question: str
    followup_count: int  # 已追问次数

    # 对话历史
    conversation_history: list[dict]

    # 报告
    summary: str
    cause_analysis: str
    solution_steps: list[str]
    references: list[dict]
    images: list[str]
    image_details: list[dict]  # 结构化图片信息 [{"path": "", "alt": "", "description": ""}]

    # 验证
    has_hallucination: bool

    # 消息历史（LangGraph 内部用）
    messages: Annotated[list[Any], add_messages]
