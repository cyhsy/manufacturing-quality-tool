"""库存域 Agent 取数封装。

调用链：``agents/*`` -> ``agent_tools/inventory_tools.py``
-> ``tools/inventory_tool.py`` -> ``data/inventory.csv``

库存状态口径复用 ``modules/inventory_analysis.py``（全项目唯一来源），
本模块只做取数与结构化，不重复实现判定规则。
"""

from agent_tools import df_to_records
from modules.inventory_analysis import (
    build_inventory_status,
    get_shortage_materials,
    summarize_inventory,
)
from tools.inventory_tool import query_inventory


def get_inventory(material=None, only_shortage=False):
    """取库存原始数据（DataFrame），委托 ``tools.inventory_tool.query_inventory()``。"""
    return query_inventory(material=material, only_shortage=only_shortage)


def get_inventory_status(material=None):
    """取带「库存状态 / 缺口」的库存表（DataFrame）。"""
    return build_inventory_status(query_inventory(material=material))


def get_inventory_records(material=None):
    """库存记录（dict 列表，含库存状态与缺口）。"""
    return df_to_records(get_inventory_status(material=material))


def get_shortage_list():
    """低于安全库存的物料记录（dict 列表，按缺口降序）。"""
    return df_to_records(get_shortage_materials())


def get_inventory_summary():
    """库存总览（dict）：物料数、预警数、正常数、预警物料名称。"""
    return summarize_inventory()


def get_material_names():
    """全部物料名称（按名称升序）。"""
    inventory = query_inventory()
    if inventory.empty:
        return []
    return sorted(str(value) for value in inventory["material"])
