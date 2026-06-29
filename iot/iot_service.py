"""
IoT 数据服务（模拟实现）
提供机床实时传感器数据查询，包装为 LlamaIndex FunctionTool 供 Agent 调用
后续可扩展为真实 IoT 平台接入（MQTT / OPC-UA）
"""

import random
from datetime import datetime

from models.schemas import MachineStatus


class IoTService:
    """IoT 数据服务"""

    # 模拟的机床列表
    MACHINES = ["VMC850-001", "VMC850-002", "VMC1060-001"]

    def get_machine_status(self, machine_id: str = "VMC850-001") -> dict:
        """
        获取机床实时状态（模拟数据）
        返回 JSON 格式的传感器数据
        """
        # 模拟异常场景
        is_abnormal = random.random() < 0.3  # 30% 概率出现异常

        status = MachineStatus(
            machine_id=machine_id,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            spindle_speed=random.uniform(0, 8000) if not is_abnormal else random.uniform(0, 12000),
            spindle_temp=random.uniform(25, 45) if not is_abnormal else random.uniform(60, 85),
            spindle_load=random.uniform(10, 60) if not is_abnormal else random.uniform(80, 110),
            feed_rate=random.uniform(0, 5000),
            coolant_pressure=random.uniform(0.3, 0.6) if not is_abnormal else random.uniform(0.05, 0.15),
            coolant_temp=random.uniform(18, 28) if not is_abnormal else random.uniform(35, 50),
            air_pressure=random.uniform(0.5, 0.7) if not is_abnormal else random.uniform(0.2, 0.35),
            vibration_x=round(random.uniform(0.1, 2.0), 3) if not is_abnormal else round(random.uniform(5.0, 12.0), 3),
            vibration_y=round(random.uniform(0.1, 2.0), 3) if not is_abnormal else round(random.uniform(5.0, 12.0), 3),
            vibration_z=round(random.uniform(0.1, 2.0), 3) if not is_abnormal else round(random.uniform(5.0, 12.0), 3),
            servo_current_x=round(random.uniform(1.0, 5.0), 2) if not is_abnormal else round(random.uniform(8.0, 15.0), 2),
            servo_current_y=round(random.uniform(1.0, 5.0), 2) if not is_abnormal else round(random.uniform(8.0, 15.0), 2),
            servo_current_z=round(random.uniform(1.0, 5.0), 2) if not is_abnormal else round(random.uniform(8.0, 15.0), 2),
            alarm_active=["SV0410", "OT0500"] if is_abnormal else [],
        )

        return status.model_dump()

    def get_sensor_data(
        self, machine_id: str = "VMC850-001", sensor_type: str = "all"
    ) -> dict:
        """
        按传感器类型查询数据
        sensor_type: all / spindle / vibration / servo / coolant / air
        """
        full_status = self.get_machine_status(machine_id)

        if sensor_type == "all":
            return full_status

        sensor_map = {
            "spindle": ["spindle_speed", "spindle_temp", "spindle_load"],
            "vibration": ["vibration_x", "vibration_y", "vibration_z"],
            "servo": ["servo_current_x", "servo_current_y", "servo_current_z"],
            "coolant": ["coolant_pressure", "coolant_temp"],
            "air": ["air_pressure"],
        }

        if sensor_type not in sensor_map:
            return {"error": f"未知传感器类型: {sensor_type}，可选: {list(sensor_map.keys())}"}

        selected_keys = sensor_map[sensor_type] + ["machine_id", "timestamp", "alarm_active"]
        return {k: v for k, v in full_status.items() if k in selected_keys}


# 全局单例
iot_service = IoTService()


# ==================== LlamaIndex FunctionTool ====================

def get_machine_status_fn(machine_id: str = "VMC850-001") -> str:
    """
    获取机床实时状态数据，包括主轴转速、温度、负载、振动、伺服电流、冷却液压力、气源压力等传感器数据。
    当需要了解机床当前运行状态或排查与传感器相关的故障时调用此函数。
    参数 machine_id: 机床编号，如 VMC850-001, VMC850-002, VMC1060-001
    """
    import json

    result = iot_service.get_machine_status(machine_id)
    return json.dumps(result, ensure_ascii=False, indent=2)


def get_sensor_data_fn(machine_id: str = "VMC850-001", sensor_type: str = "all") -> str:
    """
    按类型查询机床传感器数据。
    参数 machine_id: 机床编号
    参数 sensor_type: 传感器类型，可选值: all(全部), spindle(主轴), vibration(振动), servo(伺服), coolant(冷却), air(气源)
    """
    import json

    result = iot_service.get_sensor_data(machine_id, sensor_type)
    return json.dumps(result, ensure_ascii=False, indent=2)
