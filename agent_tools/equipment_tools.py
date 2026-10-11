"""设备域 Agent 取数封装。

调用链：

    agents/equipment_agent.py
        -> agent_tools/equipment_tools.py
            -> tools/equipment_tool.py       设备台账（data/equipment.csv）
            -> tools/iot_sensor_tool.py      传感器数据（data/iot_sensor.csv）
            -> modules/equipment_analysis.py 状态判定与维保口径
            -> modules/equipment_knowledge.py 故障案例库检索（knowledge/equipment/）
"""

import pandas as pd

from agent_tools import df_to_records, to_jsonable
from modules.equipment_analysis import (
    DEFAULT_MAINTENANCE_INTERVAL_DAYS,
    get_abnormal_equipment,
    get_maintenance_due,
    get_status_breakdown,
    summarize_equipment,
)
from modules.equipment_knowledge import search_equipment_knowledge
from tools.equipment_tool import STATUS_LABELS, query_equipment_status
from tools.iot_sensor_tool import query_latest_sensor_reading, query_sensor_readings
from tools.production_tool import query_production_capacity


def get_equipment(equipment_id=None, status=None, only_abnormal=False):
    """取设备台账（DataFrame），委托 ``tools.equipment_tool.query_equipment_status()``。"""
    return query_equipment_status(
        equipment_id=equipment_id,
        status=status,
        only_abnormal=only_abnormal,
    )


def get_equipment_records(equipment_id=None, status=None, only_abnormal=False):
    """设备记录（dict 列表）。"""
    return df_to_records(
        get_equipment(equipment_id=equipment_id, status=status, only_abnormal=only_abnormal)
    )


def get_equipment_summary(today=None):
    """设备总览（dict），复用 ``modules.equipment_analysis.summarize_equipment()``。"""
    return to_jsonable(summarize_equipment(today=today))


def get_status_breakdown_records():
    """按设备状态汇总的记录（dict 列表）。"""
    return df_to_records(get_status_breakdown())


def get_abnormal_list():
    """预警与故障设备记录（dict 列表，故障优先）。"""
    return df_to_records(get_abnormal_equipment())


def get_maintenance_due_list(days=DEFAULT_MAINTENANCE_INTERVAL_DAYS, today=None):
    """维保超期设备记录（dict 列表，按未保养天数降序）。"""
    return df_to_records(get_maintenance_due(days=days, today=today))


def get_sensor_readings(equipment_id=None, only_alarm=False):
    """取设备传感器数据（DataFrame），委托 ``tools.iot_sensor_tool.query_sensor_readings()``。"""
    return query_sensor_readings(equipment_id=equipment_id, only_alarm=only_alarm)


def get_latest_sensor_reading(equipment_id=None):
    """取最新一条传感器读数（dict），委托 ``tools.iot_sensor_tool``。"""
    return to_jsonable(query_latest_sensor_reading(equipment_id=equipment_id))


def get_equipment_production_status(equipment_id):
    """取该设备在 MES 中的产线段记录（dict 列表），用于判断停机/保养状态。"""
    lines = query_production_capacity(equipment=equipment_id)
    return df_to_records(lines)


def search_fault_knowledge(observation, limit=3):
    """检索设备故障案例库（knowledge/equipment/）。

    委托 ``modules/equipment_knowledge.search_equipment_knowledge()``；
    置信度为「与知识库案例的相似度」，不是工程失效概率。
    """
    return to_jsonable(search_equipment_knowledge(observation, limit=limit))


def get_fault_knowledge_count():
    """知识库案例总数（便于自检与展示）。"""
    from modules.equipment_knowledge import load_equipment_cases

    return len(load_equipment_cases())


def get_sensor_summary():
    """传感器数据总览：记录数、设备数、最新采集时间、告警记录数。"""
    sensor_df = get_sensor_readings()
    if sensor_df.empty:
        return {
            "record_count": 0,
            "equipment_count": 0,
            "latest_timestamp": None,
            "alarm_count": 0,
            "alarm_equipment": [],
        }

    timestamps = pd.to_datetime(sensor_df["timestamp"], errors="coerce").dropna()
    alarms = get_sensor_readings(only_alarm=True)

    return {
        "record_count": int(len(sensor_df)),
        "equipment_count": int(sensor_df["equipment_id"].nunique()),
        "latest_timestamp": None if timestamps.empty else timestamps.max().isoformat(),
        "alarm_count": int(len(alarms)),
        "alarm_equipment": sorted({str(value) for value in alarms["equipment_id"]}),
    }


def get_sensor_alarm_records():
    """传感器告警记录（dict 列表）。"""
    return df_to_records(get_sensor_readings(only_alarm=True))


def get_status_labels():
    """设备状态英文值 -> 中文标签映射。"""
    return dict(STATUS_LABELS)
