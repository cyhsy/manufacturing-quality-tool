"""设备域 Agent 取数封装。

调用链：``agents/equipment_agent.py`` -> ``agent_tools/equipment_tools.py``
-> ``tools/equipment_tool.py``（设备台账）与 ``tools.read_data_csv()``（传感器数据）-> ``data/*.csv``

设备状态判定与维保口径复用 ``modules/equipment_analysis.py``。
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
from tools import read_data_csv
from tools.equipment_tool import STATUS_LABELS, query_equipment_status


SENSOR_FILE_NAME = "iot_sensor.csv"
SENSOR_COLUMNS = [
    "timestamp",
    "equipment_id",
    "temperature",
    "vibration",
    "current",
    "status",
]
SENSOR_ALARM_STATUSES = ("warning", "alarm")


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
    """取设备传感器数据（DataFrame），经 ``tools.read_data_csv()`` 读取。"""
    sensor_df = read_data_csv(SENSOR_FILE_NAME, SENSOR_COLUMNS)

    if equipment_id is not None:
        target = str(equipment_id)
        sensor_df = sensor_df.loc[sensor_df["equipment_id"].astype(str) == target]

    if only_alarm:
        alarm_statuses = {value.lower() for value in SENSOR_ALARM_STATUSES}
        sensor_df = sensor_df.loc[
            sensor_df["status"].astype(str).str.lower().isin(alarm_statuses)
        ]

    return sensor_df.reset_index(drop=True)


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
