"""库存分析：原材料库存状态口径（data/inventory.csv）。

库存口径（全项目唯一来源，app.py 与 agent_tools 均复用本模块，避免出现两套判定）：

- ``stock >= safety_stock``            -> 「正常」
- ``stock <  safety_stock``            -> 「预警」
- 缺口 = ``max(safety_stock - stock, 0)``
"""

import pandas as pd

from tools.inventory_tool import query_inventory


INVENTORY_STATUS_COLUMN = "库存状态"
INVENTORY_GAP_COLUMN = "缺口"
STATUS_NORMAL = "正常"
STATUS_WARNING = "预警"


def build_inventory_status(inventory_df=None):
    """补充「库存状态」与「缺口」两列。

    参数：
        inventory_df: 可选，库存 DataFrame；缺省时读取 data/inventory.csv。

    返回：
        pandas.DataFrame（在原始字段基础上追加库存状态与缺口）。
    """
    df = query_inventory() if inventory_df is None else inventory_df
    if df.empty:
        return df.copy()

    result = df.copy()
    stock = pd.to_numeric(result["stock"], errors="coerce").fillna(0)
    safety_stock = pd.to_numeric(result["safety_stock"], errors="coerce").fillna(0)

    result[INVENTORY_GAP_COLUMN] = (safety_stock - stock).clip(lower=0).astype("int64")
    result[INVENTORY_STATUS_COLUMN] = STATUS_NORMAL
    result.loc[stock < safety_stock, INVENTORY_STATUS_COLUMN] = STATUS_WARNING
    return result


def get_shortage_materials(inventory_df=None):
    """返回低于安全库存的物料（按缺口降序）。"""
    inventory = build_inventory_status(inventory_df)
    if inventory.empty:
        return inventory

    shortage = inventory.loc[inventory[INVENTORY_STATUS_COLUMN] == STATUS_WARNING]
    return (
        shortage.sort_values(INVENTORY_GAP_COLUMN, ascending=False)
        .reset_index(drop=True)
    )


def summarize_inventory(inventory_df=None):
    """库存总览：物料数、预警数、正常数与预警物料名称列表。"""
    inventory = build_inventory_status(inventory_df)
    if inventory.empty:
        return {
            "material_count": 0,
            "shortage_count": 0,
            "normal_count": 0,
            "shortage_materials": [],
        }

    shortage = inventory.loc[inventory[INVENTORY_STATUS_COLUMN] == STATUS_WARNING]
    return {
        "material_count": int(len(inventory)),
        "shortage_count": int(len(shortage)),
        "normal_count": int(len(inventory) - len(shortage)),
        "shortage_materials": [str(value) for value in shortage["material"]],
    }
