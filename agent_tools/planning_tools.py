"""生产计划工具（S5-A-02）。

函数：``generate_production_plan()``

考虑：**订单数量、交付时间、当前产能、故障设备、库存风险**。

取数与依赖（全部经已有封装，不新增数据访问路径）：

    agent_tools.order_tools.get_order() / get_production_lines()   订单需求与产能取数
    tools.production_tool.query_production_capacity()             当前产能（MES 产线）
    tools.equipment_tool.query_equipment_status()                 设备状态（故障设备）
    tools.inventory_tool.query_inventory()                        库存
    data/bom.csv                                                  物料用量（本单物料需求）
    modules.planning_engine.build_production_plan()                排产规则模型（S5-A-03）
"""

import math

import pandas as pd

from agent_tools import equipment_tools, order_tools, to_jsonable
from modules.inventory_analysis import build_inventory_status
from modules.planning_engine import build_production_plan as build_plan_by_rules
from modules.planning_engine import evaluate_effective_capacity
from tools import read_data_csv
from tools.inventory_tool import query_inventory
from tools.production_tool import query_production_capacity


BOM_FILE_NAME = "bom.csv"
BOM_COLUMNS = ["product", "material", "unit_usage", "unit"]


def load_bom(product=None):
    """读取 BOM（data/bom.csv），可按产品筛选。"""
    bom = read_data_csv(BOM_FILE_NAME, BOM_COLUMNS)
    if product is not None:
        bom = bom.loc[bom["product"].astype(str) == str(product)]
    return bom


def get_equipment_status_map():
    """设备编号 -> 设备状态。"""
    return {
        str(record["equipment_id"]): str(record["status"]).strip().lower()
        for record in equipment_tools.get_equipment_records()
    }


def build_material_requirements(product, quantity, inventory_df=None):
    """按 BOM 计算本单物料需求与缺口（考虑安全库存）。"""
    bom = load_bom(product=product)
    if bom.empty:
        return []

    inventory = build_inventory_status(
        query_inventory() if inventory_df is None else inventory_df
    )

    requirements = []
    for _, row in bom.iterrows():
        material = str(row["material"])
        unit_usage = float(
            pd.to_numeric(pd.Series([row["unit_usage"]]), errors="coerce").fillna(0).iloc[0]
        )
        required = int(math.ceil(unit_usage * int(quantity)))

        matched = inventory.loc[inventory["material"].astype(str) == material]
        if matched.empty:
            stock = 0
            safety_stock = 0
        else:
            stock = int(pd.to_numeric(matched["stock"], errors="coerce").fillna(0).max())
            safety_stock = int(
                pd.to_numeric(matched["safety_stock"], errors="coerce").fillna(0).max()
            )

        stock_after = stock - required
        requirements.append(
            {
                "material": material,
                "required": required,
                "stock": stock,
                "safety_stock": safety_stock,
                "shortage": max(required - stock, 0),
                "unit": str(row["unit"]),
                "unit_usage": unit_usage,
                "stock_after": stock_after,
                "below_safety_after": stock_after < safety_stock,
                "in_inventory": not matched.empty,
            }
        )

    return requirements


def build_alternatives(product_lines, equipment_status=None):
    """为产品工序链的每个工序构建替代设备候选（同工序的其它产线）。"""
    statuses = get_equipment_status_map() if equipment_status is None else equipment_status
    production = query_production_capacity()

    alternatives = {}
    for process in {str(value) for value in product_lines["process"]}:
        lines = production.loc[production["process"].astype(str) == process]
        candidates = []
        for _, row in lines.iterrows():
            equipment = str(row["equipment"])
            production_status = str(row["status"]).strip().lower()
            equipment_state = str(statuses.get(equipment, "unknown")).strip().lower()
            candidates.append(
                {
                    "equipment": equipment,
                    "daily_capacity": int(
                        pd.to_numeric(
                            pd.Series([row["daily_capacity"]]), errors="coerce"
                        ).fillna(0).iloc[0]
                    ),
                    "blocked": production_status == "stopped" or equipment_state == "fault",
                    "status": production_status,
                    "equipment_status": equipment_state,
                }
            )
        alternatives[process] = candidates

    return alternatives


def generate_production_plan(
    order_id=None,
    product=None,
    quantity=None,
    delivery_days=None,
    deadline=None,
    today=None,
    priority=None,
    quality_risk=None,
):
    """生成生产计划（S5-A-02）。

    参数：
        order_id:      订单编号；提供时自动取该订单的产品/数量/交期/优先级。
        product:       产品名称（未给 order_id 时必填）。
        quantity:      数量（未给 order_id 时必填）。
        delivery_days: 今天起 N 天内交付（与 deadline 二选一）。
        deadline:      交付日期（ISO 字符串 / 日期对象）。
        today:         参考日期，缺省系统当天。
        priority:      优先级（high / normal / low），缺省取订单优先级或 normal。
        quality_risk:  可选，``{"risk": ..., "reason": ...}``（来自质量 Agent）。

    返回 dict：订单上下文 + 排产结果（timeline / material / capacity / schedule /
    plan_lines / risks / suggestions / status），可直接 JSON 序列化。
    """
    reference = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.today().normalize()

    order = order_tools.get_order(order_id) if order_id else None
    if order:
        product = product or order.get("product")
        quantity = quantity if quantity is not None else order.get("quantity")
        deadline = deadline or order.get("deadline")
        priority = priority or order.get("priority")

    if not product or quantity is None:
        return {
            "status": "error",
            "reason": "缺少产品与数量（或有效的订单编号），无法排产",
            "order_id": order_id,
            "suggestion": "请提供订单编号，或给出产品与数量（例如：10000 件电机壳体，15 天交付）",
        }

    quantity = int(quantity)
    if delivery_days is not None:
        deadline = (reference + pd.Timedelta(days=int(delivery_days))).date().isoformat()

    lines = order_tools.get_production_lines(product=product)
    equipment_status = get_equipment_status_map()
    capacity = evaluate_effective_capacity(lines, equipment_status)

    alternatives = build_alternatives(lines, equipment_status) if not lines.empty else {}
    material_requirements = build_material_requirements(product, quantity)

    plan = build_plan_by_rules(
        product=product,
        quantity=quantity,
        deadline=deadline,
        today=reference,
        priority=priority or "normal",
        capacity=capacity,
        alternatives=alternatives,
        material_requirements=material_requirements,
        quality_risk=quality_risk,
    )

    plan["order_id"] = order_id
    plan["order"] = order
    plan["order_source"] = "erp_order" if order else "request"
    plan["sources"] = {
        "order": "agent_tools.order_tools.get_order() -> tools.order_tool.query_orders()",
        "production": (
            "agent_tools.order_tools.get_production_lines() -> "
            "tools.production_tool.query_production_capacity()"
        ),
        "equipment": (
            "agent_tools.equipment_tools.get_equipment_records() -> "
            "tools.equipment_tool.query_equipment_status()"
        ),
        "inventory": "tools.inventory_tool.query_inventory() + modules.inventory_analysis",
        "bom": BOM_FILE_NAME,
        "engine": "modules.planning_engine.build_production_plan()",
    }

    return to_jsonable(plan)


def list_bom_products():
    """BOM 覆盖的产品（升序）。"""
    bom = load_bom()
    return sorted({str(value) for value in bom["product"]})


def get_material_requirement(product, quantity):
    """单产品的物料需求（dict 列表）。"""
    return to_jsonable(build_material_requirements(product, quantity))
