"""库存数据读取工具：原材料库存模拟数据（data/inventory.csv）。

字段口径：
    material      物料名称
    stock         当前库存量
    safety_stock  安全库存（低于该值视为库存预警）
    unit          计量单位
"""

import pandas as pd

from tools import filter_by_values, read_data_csv


INVENTORY_COLUMNS = ["material", "stock", "safety_stock", "unit"]


def query_inventory(material=None, only_shortage=False):
    """查询当前库存。

    参数：
        material:      物料筛选，单值或列表，如 "铝合金"。
        only_shortage: True 时只返回低于安全库存（stock < safety_stock）的物料。

    返回：
        pandas.DataFrame，字段与 inventory.csv 一致；
        无匹配记录时返回同结构空表。
    """
    df = read_data_csv("inventory.csv", INVENTORY_COLUMNS)

    df = filter_by_values(df, "material", material)

    if only_shortage:
        stock = pd.to_numeric(df["stock"], errors="coerce")
        safety_stock = pd.to_numeric(df["safety_stock"], errors="coerce")
        df = df.loc[stock < safety_stock]

    return df.reset_index(drop=True)
