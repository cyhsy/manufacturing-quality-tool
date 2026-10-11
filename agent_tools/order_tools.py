"""订单域 Agent 取数封装。

调用链：``agents/order_agent.py`` -> ``agent_tools/order_tools.py``
-> ``tools/order_tool.py`` / ``tools/production_tool.py`` -> ``data/*.csv``

说明：生产能力的取数也归入本模块——v1 的 agent_tools 未单列 production_tools.py，
而订单可交付分析必须同时用到订单、库存与产能（见 ``agents/order_agent.py``）。
本模块只做取数与结构化，不做风险判定。
"""

import pandas as pd

from agent_tools import df_to_records, to_jsonable
from modules.order_analysis import get_priority_breakdown, summarize_orders
from modules.production_analysis import summarize_production
from tools.order_tool import PRIORITY_LABELS, query_orders
from tools.production_tool import query_production_capacity


def get_orders(
    priority=None,
    customer=None,
    product=None,
    order_id=None,
    sort_by_deadline=False,
):
    """取订单数据（DataFrame），委托 ``tools.order_tool.query_orders()``。"""
    return query_orders(
        priority=priority,
        customer=customer,
        product=product,
        order_id=order_id,
        sort_by_deadline=sort_by_deadline,
    )


def get_order(order_id):
    """取单张订单（dict），未找到时返回 None。"""
    orders = query_orders(order_id=order_id)
    records = df_to_records(orders)
    return records[0] if records else None


def list_order_ids():
    """全部订单编号（按编号升序）。"""
    orders = query_orders()
    if orders.empty:
        return []
    return sorted(str(value) for value in orders["order_id"])


def list_order_records(limit=None, sort_by_deadline=False):
    """订单记录（dict 列表），可按最近交期排序并截断。"""
    orders = query_orders(sort_by_deadline=sort_by_deadline)
    if limit is not None and limit > 0:
        orders = orders.head(limit)
    return df_to_records(orders)


def get_priority_labels():
    """优先级英文值 -> 中文标签映射。"""
    return dict(PRIORITY_LABELS)


def get_production_lines(product=None, process=None, equipment=None, only_running=False):
    """取 MES 产线数据（DataFrame），委托 ``tools.production_tool.query_production_capacity()``。"""
    return query_production_capacity(
        product=product,
        process=process,
        equipment=equipment,
        only_running=only_running,
    )


def get_factory_capacity():
    """全厂产能总览（dict），复用 ``modules.production_analysis.summarize_production()``。

    用于「该产品在 MES 中没有产线」时回退测算全厂可交付能力。
    """
    return to_jsonable(summarize_production())


def get_order_summary():
    """订单总览（dict），复用 ``modules.order_analysis.summarize_orders()``。"""
    return to_jsonable(summarize_orders())


def get_priority_breakdown_records():
    """订单优先级分布记录（dict 列表）。"""
    return df_to_records(get_priority_breakdown())


def list_products():
    """全部已知产品名称（订单 ∪ MES 产线），按名称长度降序（长名优先匹配）。"""
    products = set()

    orders = query_orders()
    if not orders.empty:
        products.update(str(value) for value in orders["product"])

    lines = query_production_capacity()
    if not lines.empty:
        products.update(str(value) for value in lines["product"])

    return sorted(products, key=lambda name: (-len(name), name))


def find_matching_orders(product=None, quantity=None, limit=5):
    """按产品（可选数量）查找在手订单，返回记录列表。

    用于把「用户口述的订单」与 ERP 在手订单做交叉引用。
    """
    orders = query_orders(product=product)
    if orders.empty:
        return []

    if quantity is not None:
        quantities = pd.to_numeric(orders["quantity"], errors="coerce")
        orders = orders.loc[quantities == quantity]

    if limit is not None and limit > 0:
        orders = orders.head(limit)

    return df_to_records(orders)
