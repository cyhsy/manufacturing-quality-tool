"""生产能力读取工具：MES 生产数据（data/production.csv）。

字段口径：
    product         产品
    process         工序
    equipment       设备编号（与 equipment.csv 的 equipment_id 对应）
    daily_capacity  日产能
    yield_rate      良率（百分比字符串，如 "96%"）
    status          产线状态（running 生产中 / idle 待机 / maintenance 保养中 / stopped 停机）
"""

from tools import filter_by_values, read_data_csv


PRODUCTION_COLUMNS = [
    "product",
    "process",
    "equipment",
    "daily_capacity",
    "yield_rate",
    "status",
]

STATUS_LABELS = {
    "running": "生产中",
    "idle": "待机",
    "maintenance": "保养中",
    "stopped": "停机",
}


def query_production_capacity(product=None, process=None, equipment=None, only_running=False):
    """查询生产能力。

    参数：
        product:       产品筛选，单值或列表。
        process:       工序筛选，单值或列表，如 "铸造"。
        equipment:     设备编号筛选，单值或列表。
        only_running:  True 时只返回 status == "running" 的产线。

    返回：
        pandas.DataFrame，字段与 production.csv 一致；
        无匹配记录时返回同结构空表。
    """
    df = read_data_csv("production.csv", PRODUCTION_COLUMNS)

    df = filter_by_values(df, "product", product)
    df = filter_by_values(df, "process", process)
    df = filter_by_values(df, "equipment", equipment)

    if only_running:
        df = filter_by_values(df, "status", "running", case_insensitive=True)

    return df.reset_index(drop=True)
