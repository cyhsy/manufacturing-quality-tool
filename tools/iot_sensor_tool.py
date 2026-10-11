"""设备传感器数据访问工具（data/iot_sensor.csv），S3-A-02 依赖。

字段口径：
    timestamp     采集时间
    equipment_id  设备编号（与 equipment.csv 的 equipment_id 对应）
    temperature   温度 ℃
    vibration     振动 mm/s
    current       电流 A
    status        采集状态（normal 正常 / warning 预警 / alarm 报警）
"""

import pandas as pd

from tools import filter_by_values, read_data_csv


SENSOR_FILE_NAME = "iot_sensor.csv"
SENSOR_COLUMNS = [
    "timestamp",
    "equipment_id",
    "temperature",
    "vibration",
    "current",
    "status",
]
ALARM_STATUSES = ("warning", "alarm")


def _to_float(value):
    """转成 float；无法解析时返回 None（避免 NaN 进入 Agent 输出）。"""
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(number) else float(number)


def query_sensor_readings(equipment_id=None, only_alarm=False):
    """查询设备传感器数据（DataFrame），按采集时间升序。

    参数：
        equipment_id: 设备编号筛选，单值或列表。
        only_alarm:   True 时只返回 warning / alarm 状态的记录。
    """
    df = read_data_csv(SENSOR_FILE_NAME, SENSOR_COLUMNS)

    df = filter_by_values(df, "equipment_id", equipment_id)

    if only_alarm:
        df = filter_by_values(df, "status", ALARM_STATUSES, case_insensitive=True)

    ordered = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.assign(_采集时间=ordered).sort_values("_采集时间").drop(columns="_采集时间")

    return df.reset_index(drop=True)


def query_latest_sensor_reading(equipment_id=None):
    """最新一条采集记录（dict）；无数据时返回 None。"""
    readings = query_sensor_readings(equipment_id=equipment_id)
    if readings.empty:
        return None

    row = readings.iloc[-1]
    return {
        "timestamp": str(row["timestamp"]),
        "equipment_id": str(row["equipment_id"]),
        "temperature": _to_float(row["temperature"]),
        "vibration": _to_float(row["vibration"]),
        "current": _to_float(row["current"]),
        "status": str(row["status"]),
    }


def query_sensor_alarms(equipment_id=None):
    """传感器告警记录（DataFrame）。"""
    return query_sensor_readings(equipment_id=equipment_id, only_alarm=True)
