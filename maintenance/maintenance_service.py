"""
历史维修记录服务（模拟实现）
提供机床历史维修记录查询，供 Agent 通过 function calling 调用
后续可替换为真实 MES/ERP 系统接口
"""

import random
from datetime import datetime, timedelta

from models.schemas import MaintenanceRecord


# 模拟维修记录数据库
_MOCK_RECORDS: list[dict] = [
    # ==================== FANUC 设备 ====================
    {
        "record_id": "MR-2024-001",
        "machine_id": "VMC850-001",
        "source": "fanuc",
        "fault_description": "SV0410 伺服报警，Z轴过载",
        "alarm_code": "SV0410",
        "maintenance_date": "2024-11-15",
        "technician": "张工",
        "root_cause": "Z轴联轴器松动，导致编码器反馈异常",
        "solution": "紧固联轴器螺栓，重新校准编码器零点",
        "parts_replaced": ["联轴器紧固螺栓x4"],
        "duration_hours": 2.5,
        "result": "resolved",
    },
    {
        "record_id": "MR-2024-002",
        "machine_id": "VMC850-001",
        "source": "fanuc",
        "fault_description": "PS0001 程序报警，宏程序变量溢出",
        "alarm_code": "PS0001",
        "maintenance_date": "2024-10-20",
        "technician": "李工",
        "root_cause": "操作人员误修改宏变量#500-#509",
        "solution": "恢复备份参数，重新初始化宏变量表",
        "parts_replaced": [],
        "duration_hours": 1.0,
        "result": "resolved",
    },
    {
        "record_id": "MR-2024-003",
        "machine_id": "VMC850-001",
        "source": "fanuc",
        "fault_description": "OT0500 过行程报警，X轴正方向超限",
        "alarm_code": "OT0500",
        "maintenance_date": "2024-09-05",
        "technician": "张工",
        "root_cause": "软限位参数MD1320被误修改",
        "solution": "恢复软限位参数，手动回机械原点",
        "parts_replaced": [],
        "duration_hours": 0.5,
        "result": "resolved",
    },
    {
        "record_id": "MR-2024-004",
        "machine_id": "VMC850-002",
        "source": "fanuc",
        "fault_description": "SV0436 电源模块过热报警",
        "alarm_code": "SV0436",
        "maintenance_date": "2024-12-01",
        "technician": "王工",
        "root_cause": "电柜散热风扇故障，内部温度过高",
        "solution": "更换散热风扇，清理滤网灰尘",
        "parts_replaced": ["轴流风扇 24V x2"],
        "duration_hours": 1.5,
        "result": "resolved",
    },
    # ==================== Siemens 设备 ====================
    {
        "record_id": "MR-2024-005",
        "machine_id": "VMC850-002",
        "source": "siemens",
        "fault_description": "25201 伺服故障，Y轴驱动器报警",
        "alarm_code": "25201",
        "maintenance_date": "2024-11-28",
        "technician": "李工",
        "root_cause": "Y轴伺服电机编码器电缆接触不良",
        "solution": "重新插拔编码器电缆，更换屏蔽层接地线",
        "parts_replaced": ["编码器电缆 x1"],
        "duration_hours": 2.0,
        "result": "resolved",
    },
    {
        "record_id": "MR-2024-006",
        "machine_id": "VMC850-002",
        "source": "siemens",
        "fault_description": "27253 主轴通信故障",
        "alarm_code": "27253",
        "maintenance_date": "2024-08-10",
        "technician": "王工",
        "root_cause": "DRIVE-CLiQ 通信电缆被铁屑割断",
        "solution": "更换 DRIVE-CLiQ 电缆，重新布线加装防护管",
        "parts_replaced": ["DRIVE-CLiQ 电缆 3m x1", "波纹管 1m"],
        "duration_hours": 3.0,
        "result": "resolved",
    },
    {
        "record_id": "MR-2024-007",
        "machine_id": "VMC1060-001",
        "source": "siemens",
        "fault_description": "300504 驱动器直流母线电压过高",
        "alarm_code": "300504",
        "maintenance_date": "2024-07-22",
        "technician": "张工",
        "root_cause": "再生制动电阻断路，制动能量无法释放",
        "solution": "更换制动电阻模块",
        "parts_replaced": ["制动电阻 100W/40Ω x1"],
        "duration_hours": 2.0,
        "result": "resolved",
    },
    # ==================== VMC850 机械故障 ====================
    {
        "record_id": "MR-2024-008",
        "machine_id": "VMC850-001",
        "source": "vmc850",
        "fault_description": "刀库换刀卡死，刀臂停在半空",
        "alarm_code": "MECH-001",
        "maintenance_date": "2024-12-05",
        "technician": "赵工",
        "root_cause": "车间气源压力不足，拔刀缸推力不够",
        "solution": "调整气动三联件压力至0.5MPa，手动盘车复位刀臂",
        "parts_replaced": [],
        "duration_hours": 1.0,
        "result": "resolved",
    },
    {
        "record_id": "MR-2024-009",
        "machine_id": "VMC850-001",
        "source": "vmc850",
        "fault_description": "主轴高速旋转异响，温度超过70℃",
        "alarm_code": "MECH-002",
        "maintenance_date": "2024-06-18",
        "technician": "赵工",
        "root_cause": "主轴前段陶瓷轴承保持架碎裂",
        "solution": "更换主轴总成，重新校准动平衡",
        "parts_replaced": ["BT40主轴总成 x1", "主轴轴承组 x1"],
        "duration_hours": 8.0,
        "result": "resolved",
    },
    {
        "record_id": "MR-2024-010",
        "machine_id": "VMC850-001",
        "source": "vmc850",
        "fault_description": "X轴低速进给爬行，加工面有震纹",
        "alarm_code": "MECH-004",
        "maintenance_date": "2024-05-10",
        "technician": "赵工",
        "root_cause": "导轨润滑油管被切屑砸扁，润滑不足",
        "solution": "更换4mm铝塑油管，补充VG68导轨油",
        "parts_replaced": ["4mm铝塑油管 2m", "VG68导轨油 5L"],
        "duration_hours": 2.0,
        "result": "resolved",
    },
]


class MaintenanceService:
    """历史维修记录查询服务"""

    def get_records_by_machine(self, machine_id: str, limit: int = 5) -> list[dict]:
        """按机床编号查询维修记录"""
        records = [r for r in _MOCK_RECORDS if r["machine_id"] == machine_id]
        records.sort(key=lambda x: x["maintenance_date"], reverse=True)
        return records[:limit]

    def get_records_by_alarm(self, alarm_code: str) -> list[dict]:
        """按报警代码查询维修记录"""
        return [r for r in _MOCK_RECORDS if r["alarm_code"] == alarm_code]

    def get_records_by_source(self, source: str, limit: int = 5) -> list[dict]:
        """按品牌查询维修记录"""
        records = [r for r in _MOCK_RECORDS if r["source"] == source]
        records.sort(key=lambda x: x["maintenance_date"], reverse=True)
        return records[:limit]

    def search_records(
        self,
        machine_id: str = "",
        alarm_code: str = "",
        source: str = "",
        keyword: str = "",
        limit: int = 5,
    ) -> list[dict]:
        """综合搜索维修记录"""
        results = list(_MOCK_RECORDS)

        if machine_id:
            results = [r for r in results if r["machine_id"] == machine_id]
        if alarm_code:
            results = [r for r in results if r["alarm_code"] == alarm_code]
        if source:
            results = [r for r in results if r["source"] == source]
        if keyword:
            keyword_lower = keyword.lower()
            results = [
                r for r in results
                if keyword_lower in r["fault_description"].lower()
                or keyword_lower in r["root_cause"].lower()
                or keyword_lower in r["solution"].lower()
            ]

        results.sort(key=lambda x: x["maintenance_date"], reverse=True)
        return results[:limit]


# 全局单例
maintenance_service = MaintenanceService()
