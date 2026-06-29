"""
LangGraph 状态图编排
定义节点之间的流转关系和条件路由
"""

import logging

from langgraph.graph import END, StateGraph

from agents.nodes import (
    router_node,
    cnc_expert_node,
    machine_expert_node,
    compound_expert_node,
    report_node,
)
from agents.state import AgentState

logger = logging.getLogger(__name__)


def _route_after_router(state: AgentState) -> str:
    """路由节点后的条件分支"""
    intent = state.get("intent", "fault_diagnosis")
    target = state.get("target_agent", "cnc_expert")

    # 闲聊直接结束
    if intent == "chitchat":
        return END

    # Router 判断需要追问（品牌不明确 / 模糊提问）
    if state.get("needs_followup"):
        return END

    # 复合故障 → 两个专家都走
    if target == "compound_expert":
        return "compound_expert"

    # 路由到对应专家
    if target == "machine_expert":
        return "machine_expert"

    return "cnc_expert"


def _route_after_expert(state: AgentState) -> str:
    """专家节点后的条件分支：追问或出报告"""
    if state.get("needs_followup"):
        return END  # 需要追问时直接结束，由 API 层处理
    return "report"


def build_graph() -> StateGraph:
    """
    构建多智能体状态图

    流程：
    router → (chitchat → END)
           → (needs_followup → END)
           → (cnc_fault → cnc_expert → [追问→END / 报告→END])
           → (mechanical_fault → machine_expert → [追问→END / 报告→END])
           → (compound_fault → compound_expert → [追问→END / 报告→END])
    """
    graph = StateGraph(AgentState)

    # 注册节点
    graph.add_node("router", router_node)
    graph.add_node("cnc_expert", cnc_expert_node)
    graph.add_node("machine_expert", machine_expert_node)
    graph.add_node("compound_expert", compound_expert_node)
    graph.add_node("report", report_node)

    # 入口
    graph.set_entry_point("router")

    # 条件路由
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {
            "cnc_expert": "cnc_expert",
            "machine_expert": "machine_expert",
            "compound_expert": "compound_expert",
            END: END,
        },
    )

    # 专家 → [追问→END / 报告→END]
    graph.add_conditional_edges(
        "cnc_expert",
        _route_after_expert,
        {
            "report": "report",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "machine_expert",
        _route_after_expert,
        {
            "report": "report",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "compound_expert",
        _route_after_expert,
        {
            "report": "report",
            END: END,
        },
    )

    # 报告 → END
    graph.add_edge("report", END)

    return graph


def get_compiled_graph():
    """获取编译后的图"""
    graph = build_graph()
    return graph.compile()
