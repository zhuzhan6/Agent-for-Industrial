"""
Agent Tools 定义
知识库检索 + IoT 数据查询，供 LangGraph agent 通过 function calling 调用
"""

from langchain_core.tools import tool

from iot.iot_service import iot_service
from maintenance.maintenance_service import maintenance_service
from rag.retriever import retrieve

# 缓存最近一次检索的结构化结果，供节点构建 references
_last_kb_results: list[dict] = []


def get_last_kb_results() -> list[dict]:
    """获取最近一次知识库检索的结构化结果"""
    return _last_kb_results


@tool
def search_knowledge_base(query: str, source: str) -> str:
    """
    检索故障知识库，返回相关的故障手册内容。
    当需要查找故障原因、排除方法、报警说明时调用此函数。

    参数 query: 检索查询，描述故障现象或报警代码
    参数 source: 知识库来源，必须指定，可选值: fanuc(FANUC数控系统), siemens(Siemens 840D), vmc850(VMC850机床机械)
    """
    import json

    # 验证 source 参数
    if source not in ("fanuc", "siemens", "vmc850"):
        return f"错误：source 参数必须是 fanuc、siemens 或 vmc850，当前值: {source}"

    results = retrieve(query=query, source=source)

    if not results:
        return "未找到相关故障信息。"

    # 缓存结构化结果，供节点构建溯源引用
    global _last_kb_results
    _last_kb_results = [
        {
            "chunk_id": r.chunk_id,
            "text": r.text[:300],
            "source": r.source,
            "section_title": r.section_title,
            "alarm_code": r.alarm_code,
            "score": round(r.score, 3),
            "images": r.images,
            "parent_images": r.parent_images,
        }
        for r in results[:5]
    ]

    output = []
    for i, r in enumerate(results[:5], 1):
        part = f"--- 结果 {i} (相似度: {r.score:.3f}) ---\n"
        part += f"来源: {r.source}\n"
        part += f"章节: {r.section_title}\n"
        if r.alarm_code:
            part += f"报警代码: {r.alarm_code}\n"
        part += f"内容: {r.text}\n"
        if r.parent_text:
            part += f"完整上下文: {r.parent_text[:500]}...\n"
        output.append(part)

    return "\n".join(output)


@tool
def get_iot_data(machine_id: str = "VMC850-001", sensor_type: str = "all") -> str:
    """
    查询机床IoT实时传感器数据，包括主轴转速、温度、负载、振动、伺服电流、冷却液、气源压力等。
    当故障诊断需要参考机床当前运行状态时调用此函数。

    参数 machine_id: 机床编号，可选值: VMC850-001, VMC850-002, VMC1060-001
    参数 sensor_type: 传感器类型，可选值: all(全部), spindle(主轴), vibration(振动), servo(伺服), coolant(冷却), air(气源)
    """
    import json

    result = iot_service.get_sensor_data(machine_id, sensor_type)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def get_maintenance_history(
    machine_id: str = "",
    alarm_code: str = "",
    source: str = "",
    keyword: str = "",
) -> str:
    """
    查询机床历史维修记录，了解同一设备或同一报警代码的历史故障和维修方案。
    当需要参考历史维修经验、判断故障是否反复出现、或查找同类故障的解决方案时调用此函数。

    参数 machine_id: 机床编号，可选值: VMC850-001, VMC850-002, VMC1060-001
    参数 alarm_code: 报警代码，如 SV0410, 27253, MECH-001
    参数 source: 设备品牌，可选值: fanuc, siemens, vmc850
    参数 keyword: 关键词，搜索故障描述/原因/方案中的关键词
    """
    import json

    results = maintenance_service.search_records(
        machine_id=machine_id,
        alarm_code=alarm_code,
        source=source,
        keyword=keyword,
    )

    if not results:
        return "未找到相关历史维修记录。"

    output = []
    for i, r in enumerate(results, 1):
        part = f"--- 记录 {i} ({r['maintenance_date']}) ---\n"
        part += f"记录ID: {r['record_id']}\n"
        part += f"机床: {r['machine_id']}\n"
        part += f"报警: {r['alarm_code']}\n"
        part += f"故障: {r['fault_description']}\n"
        part += f"原因: {r['root_cause']}\n"
        part += f"方案: {r['solution']}\n"
        if r["parts_replaced"]:
            part += f"换件: {', '.join(r['parts_replaced'])}\n"
        part += f"耗时: {r['duration_hours']}h | 维修人: {r['technician']} | 结果: {r['result']}\n"
        output.append(part)

    return "\n".join(output)
