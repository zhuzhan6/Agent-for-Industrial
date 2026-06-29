"""
数据模型定义
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ==================== 枚举 ====================


class SourceType(str, Enum):
    FANUC = "fanuc"
    SIEMENS = "siemens"
    VMC850 = "vmc850"


class IntentType(str, Enum):
    CHITCHAT = "chitchat"
    FAULT_DIAGNOSIS = "fault_diagnosis"


class FaultType(str, Enum):
    CNC_FAULT = "cnc_fault"
    MECHANICAL_FAULT = "mechanical_fault"
    UNKNOWN = "unknown"


class AgentType(str, Enum):
    CNC_EXPERT = "cnc_expert"
    MACHINE_EXPERT = "machine_expert"


# ==================== IoT 数据模型 ====================


class MachineStatus(BaseModel):
    """机床实时状态"""
    machine_id: str = Field(..., description="机床ID")
    timestamp: str = Field(..., description="时间戳")
    spindle_speed: float = Field(0, description="主轴转速 (rpm)")
    spindle_temp: float = Field(0, description="主轴温度 (℃)")
    spindle_load: float = Field(0, description="主轴负载 (%)")
    feed_rate: float = Field(0, description="进给速度 (mm/min)")
    coolant_pressure: float = Field(0, description="冷却液压力 (MPa)")
    coolant_temp: float = Field(0, description="冷却液温度 (℃)")
    air_pressure: float = Field(0, description="气源压力 (MPa)")
    vibration_x: float = Field(0, description="X轴振动 (mm/s)")
    vibration_y: float = Field(0, description="Y轴振动 (mm/s)")
    vibration_z: float = Field(0, description="Z轴振动 (mm/s)")
    servo_current_x: float = Field(0, description="X轴伺服电流 (A)")
    servo_current_y: float = Field(0, description="Y轴伺服电流 (A)")
    servo_current_z: float = Field(0, description="Z轴伺服电流 (A)")
    alarm_active: list[str] = Field(default_factory=list, description="当前活跃报警")


class SensorQuery(BaseModel):
    """传感器查询参数"""
    machine_id: str = Field("VMC850-001", description="机床ID")
    sensor_type: str = Field(
        "all",
        description="传感器类型: all/spindle/vibration/servo/coolant/air",
    )


class MaintenanceRecord(BaseModel):
    """历史维修记录"""
    record_id: str = Field("", description="维修记录ID")
    machine_id: str = Field("", description="机床ID")
    source: str = Field("", description="设备品牌: fanuc/siemens/vmc850")
    fault_description: str = Field("", description="故障描述")
    alarm_code: str = Field("", description="报警代码")
    maintenance_date: str = Field("", description="维修日期")
    technician: str = Field("", description="维修人员")
    root_cause: str = Field("", description="根本原因")
    solution: str = Field("", description="维修方案")
    parts_replaced: list[str] = Field(default_factory=list, description="更换零件")
    duration_hours: float = Field(0, description="维修耗时(小时)")
    result: str = Field("", description="维修结果: resolved/unresolved/partial")


# ==================== 检索结果 ====================


class ImageInfo(BaseModel):
    """图片信息"""
    path: str = Field("", description="图片路径")
    alt: str = Field("", description="图片alt文本")
    description: str = Field("", description="图片上下文描述")


class RetrievalResult(BaseModel):
    """检索结果"""
    chunk_id: str = Field("")
    text: str = Field("")
    source: str = Field("")
    section_title: str = Field("")
    alarm_code: str = Field("")
    images: list[str] = Field(default_factory=list, description="图片路径列表")
    score: float = Field(0.0)
    parent_text: str = Field("")
    parent_images: list[str] = Field(default_factory=list)


# ==================== API 模型 ====================


class DiagnoseRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户问题")
    session_id: Optional[str] = Field(None, description="会话ID，用于多轮对话")


class DiagnoseResponse(BaseModel):
    session_id: str = Field("", description="会话ID")
    question: str = Field("")
    summary: str = Field("")
    cause_analysis: str = Field("")
    solution_steps: list[str] = Field(default_factory=list)
    references: list[dict] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list, description="图片路径列表（兼容旧版）")
    image_details: list[ImageInfo] = Field(default_factory=list, description="结构化图片信息")
    iot_data: Optional[dict] = Field(None, description="IoT实时数据")
    confidence: float = Field(0.0)
    has_hallucination: bool = Field(False)
    router_decision: dict = Field(default_factory=dict)
    needs_followup: bool = Field(False, description="是否需要追问")
    followup_question: str = Field("", description="追问问题")


class IngestRequest(BaseModel):
    source: Optional[str] = Field(None, description="fanuc/siemens/vmc850, None=全部")
    force_rebuild: bool = Field(False)


class HealthResponse(BaseModel):
    status: str = "ok"
    qdrant_connected: bool = False
    index_loaded: bool = False
