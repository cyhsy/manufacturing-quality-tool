"""设备数据读取工具：设备台账模拟数据（data/equipment.csv）。

字段口径：
    equipment_id      设备编号（与 production.csv 的 equipment 字段对应）
    equipment_type    设备类型
    status            设备状态（normal 正常 / warning 预警 / fault 故障）
    capacity          日产能
    last_maintenance  上次保养日期（ISO 格式 YYYY-MM-DD）
"""

from tools import filter_by_values, read_data_csv


EQUIPMENT_COLUMNS = [
    "equipment_id",
    "equipment_type",
    "status",
    "capacity",
    "last_maintenance",
]

ABNORMAL_STATUS_VALUES = ("warning", "fault")
STATUS_LABELS = {"normal": "正常", "warning": "预警", "fault": "故障"}


def query_equipment_status(equipment_id=None, status=None, only_abnormal=False):
    """查询设备状态。

    参数：
        equipment_id:  设备编号筛选，单值或列表。
        status:        设备状态筛选，单值或列表，如 "warning"。
        only_abnormal: True 时只返回非 normal（预警 + 故障）的设备。

    返回：
        pandas.DataFrame，字段与 equipment.csv 一致；
        无匹配记录时返回同结构空表。
    """
    df = read_data_csv("equipment.csv", EQUIPMENT_COLUMNS)

    df = filter_by_values(df, "equipment_id", equipment_id)
    df = filter_by_values(df, "status", status, case_insensitive=True)

    if only_abnormal:
        df = filter_by_values(df, "status", ABNORMAL_STATUS_VALUES, case_insensitive=True)

    return df.reset_index(drop=True)
