"""Order Agent：订单可交付分析（S2-A-04）。

两个入口共用同一套交付判定口径：

- ``analyze_order_delivery(order_id)``  —— 分析 ERP 里的在手订单（如 O001）；
- ``analyze_order_request(product, quantity, delivery_days/deadline)``
  —— 分析「用户在对话里口述的订单」（如「工厂收到10000件电机壳体订单，15天交付」），
  这类输入没有订单编号，但仍必须回答「这一单有没有风险」。

取数来源（全部经 agent_tools 封装，不直接读 CSV）：

- ``agent_tools.order_tools.get_orders()``            -> ``tools.order_tool.query_orders()``
- ``agent_tools.order_tools.get_production_lines()`` -> ``tools.production_tool.query_production_capacity()``
- ``agent_tools.inventory_tools.get_shortage_list()``-> ``tools.inventory_tool.query_inventory()``
- ``agent_tools.equipment_tools.get_equipment_records()`` -> ``tools.equipment_tool.query_equipment_status()``

交付判定模型（v1，简单、可解释）：

1. 取该产品在 MES 中的各道工序产线，逐条计算「有效日产能」：
   产线停机（``stopped``）或设备故障（``fault``）时记为 0，否则取 ``daily_capacity``。
2. 瓶颈产能 = 各工序有效日产能的最小值（同一产品的工序串行，产能由最慢工序决定）。
   若该产品在 MES 中没有产线，则回退为全厂在产日产能，并在 notes 中标注。
3. 所需天数 = ``ceil(订单数量 / 瓶颈产能)``。
4. 风险判定：

   ========================  ==========================================
   条件                       风险
   ========================  ==========================================
   关键工序有效产能为 0        high（工序不可用）
   所需天数 > 交期剩余天数      high（产能不足）
   所需天数 > 0.8 × 剩余天数    medium（交期紧张）
   存在预警/保养设备            medium（设备降额风险）
   近交期（<=14 天）且有物料预警 风险上调一级
   其余                        low
   ========================  ==========================================
"""

import math

import pandas as pd

from agent_tools import df_to_records, equipment_tools, inventory_tools, order_tools


NEAR_TERM_DAYS = 14
TIGHT_RATIO = 0.8
DERATED_PRODUCTION_STATUSES = ("maintenance", "idle")
DERATED_EQUIPMENT_STATUSES = ("warning",)
RISK_ORDER = ["low", "medium", "high"]


def _escalate(risk):
    """把风险等级上调一级（low -> medium -> high）。"""
    if risk not in RISK_ORDER:
        return risk
    return RISK_ORDER[min(RISK_ORDER.index(risk) + 1, len(RISK_ORDER) - 1)]


def _reference_day(today=None):
    return (
        pd.Timestamp(today).normalize()
        if today is not None
        else pd.Timestamp.today().normalize()
    )


def evaluate_capacity(product):
    """评估某产品的产能：返回瓶颈日产能、产线明细与受阻/降额工序。"""
    lines = order_tools.get_production_lines(product=product)
    equipment_status = {
        str(record["equipment_id"]): str(record["status"]).lower()
        for record in equipment_tools.get_equipment_records()
    }

    if lines.empty:
        return {
            "source": "factory_running_capacity",
            "bottleneck": None,
            "lines": [],
            "blocked_lines": [],
            "derated_lines": [],
        }

    evaluated = lines.copy()
    evaluated["effective_capacity"] = (
        pd.to_numeric(evaluated["daily_capacity"], errors="coerce").fillna(0).astype("int64")
    )
    production_status = evaluated["status"].astype(str).str.lower()
    evaluated["equipment_status"] = (
        evaluated["equipment"].astype(str).map(lambda value: equipment_status.get(value, "unknown"))
    )
    equipment_state = evaluated["equipment_status"]

    blocked_mask = (production_status == "stopped") | (equipment_state == "fault")
    derated_mask = (
        production_status.isin(DERATED_PRODUCTION_STATUSES)
        | equipment_state.isin(DERATED_EQUIPMENT_STATUSES)
    ) & (~blocked_mask)

    evaluated.loc[blocked_mask, "effective_capacity"] = 0
    evaluated["blocked"] = blocked_mask
    evaluated["derated"] = derated_mask

    detail_columns = [
        "process",
        "equipment",
        "status",
        "equipment_status",
        "daily_capacity",
        "effective_capacity",
        "blocked",
        "derated",
    ]
    line_details = df_to_records(evaluated[detail_columns])

    return {
        "source": "product_process_bottleneck",
        "bottleneck": int(evaluated["effective_capacity"].min()),
        "lines": line_details,
        "blocked_lines": [item for item in line_details if item["blocked"]],
        "derated_lines": [item for item in line_details if item["derated"]],
    }


def evaluate_delivery(product, quantity, deadline, today=None, extra_notes=None):
    """交付测算核心：给定 产品 / 数量 / 交期，产出 risk / reason / suggestion 与依据。

    该函数不关心订单来自哪里（ERP 订单行，或用户在对话里口述的订单），
    因此 ``analyze_order_delivery()`` 与 ``analyze_order_request()`` 共用同一套判定口径。
    """
    reference = _reference_day(today)
    has_deadline = deadline is not None and not pd.isna(deadline)
    available_days = int((deadline - reference).days) if has_deadline else None

    capacity = evaluate_capacity(product)
    bottleneck = capacity["bottleneck"]
    if bottleneck is None:
        factory_capacity = order_tools.get_factory_capacity()
        bottleneck = int(factory_capacity.get("running_daily_capacity", 0))

    required_days = math.ceil(quantity / bottleneck) if bottleneck > 0 else None

    shortage = inventory_tools.get_shortage_list()
    material_summary = inventory_tools.get_inventory_summary()

    reason_parts = []
    notes = list(extra_notes or [])

    # ---------- 主判定：产能可行性与工序可用性 ----------
    if capacity["blocked_lines"]:
        risk = "high"
        blocked_text = "、".join(
            f"{item['process']}/{item['equipment']}" for item in capacity["blocked_lines"]
        )
        reason_parts.append(
            f"关键工序不可用（产线停机或设备故障）：{blocked_text}，无法形成完整产出"
        )
        suggestion = "启用替代设备或外协加工，并重新排产后更新交期"
    elif required_days is None:
        risk = "high"
        reason_parts.append(f"瓶颈日产能为 0（{capacity['source']}），无法测算可交付能力")
        suggestion = "确认产线与设备可用状态后重新排产"
    elif available_days is None:
        risk = "medium"
        reason_parts.append("缺少有效交付日期，无法判定交期风险")
        suggestion = "补齐交付日期后重新评估"
    elif required_days > available_days:
        risk = "high"
        reason_parts.append(
            f"产能不足：瓶颈日产能 {bottleneck} 件，完成 {quantity} 件约需 {required_days} 天，"
            f"超过交期剩余 {available_days} 天"
        )
        suggestion = "调整排产：增加班次、切换替代设备或安排外协"
    else:
        risk = "low"
        reason_parts.append(
            f"产能可满足：瓶颈日产能 {bottleneck} 件，完成 {quantity} 件约需 {required_days} 天，"
            f"交期剩余 {available_days} 天"
        )
        suggestion = "按现有排产执行"
        if required_days > available_days * TIGHT_RATIO:
            risk = "medium"
            reason_parts.append("交期较紧，建议提前锁定工序资源")
            suggestion = "优先排产并预留缓冲时间"
        elif capacity["derated_lines"]:
            risk = "medium"
            derated_text = "、".join(
                f"{item['process']}/{item['equipment']}" for item in capacity["derated_lines"]
            )
            reason_parts.append(
                f"部分工序设备处于预警或保养状态（{derated_text}），实际产能可能下降"
            )
            suggestion = "排产前确认设备可用状态，必要时先安排维保"

    if risk == "low" and has_deadline:
        suggestion = f"按现有排产执行，锁定 {deadline.date().isoformat()} 交付节点"

    # ---------- 物料维度：近交期订单受当前物料预警影响，风险上调一级 ----------
    if available_days is not None and available_days <= NEAR_TERM_DAYS and shortage:
        escalated = _escalate(risk)
        if escalated != risk:
            reason_parts.append(
                f"近交期订单（剩余 {available_days} 天）且全厂有 {len(shortage)} 项物料低于安全库存，"
                f"风险由 {risk} 上调为 {escalated}"
            )
        risk = escalated

    # ---------- 说明事项 ----------
    if shortage:
        notes.append(
            f"全厂物料预警 {len(shortage)} 项："
            + "、".join(str(item["material"]) for item in shortage)
        )
    if capacity["source"] == "factory_running_capacity":
        notes.append("该产品在 data/production.csv 中没有对应产线，已回退为全厂在产日产能测算")
    notes.append("本分析按单订单瓶颈产能测算，未计入其它在制订单的产能占用")

    return {
        "risk": risk,
        "reason": "；".join(reason_parts),
        "suggestion": suggestion,
        "product": product,
        "quantity": quantity,
        "deadline": deadline.date().isoformat() if has_deadline else None,
        "available_days": available_days,
        "required_days": required_days,
        "bottleneck_daily_capacity": bottleneck,
        "capacity_source": capacity["source"],
        "capacity_lines": capacity["lines"],
        "material_summary": material_summary,
        "notes": notes,
    }


def analyze_order_delivery(order_id, today=None):
    """分析 ERP 在手订单的可交付性（入口 1）。

    返回 dict：在 ``evaluate_delivery()`` 结果基础上增加
    ``order_id`` / ``priority`` / ``order_source="erp_order"``。
    """
    orders = order_tools.get_orders()
    if orders.empty:
        return {
            "order_id": order_id,
            "risk": "unknown",
            "reason": "订单数据为空，无法分析",
            "suggestion": "请检查 data/orders.csv 是否存在有效数据",
            "notes": [],
        }

    matched = orders.loc[
        orders["order_id"].astype(str).str.upper() == str(order_id).upper()
    ]
    if matched.empty:
        return {
            "order_id": order_id,
            "risk": "unknown",
            "reason": f"未找到订单 {order_id}",
            "suggestion": "请核对订单编号后重试",
            "notes": [f"可用订单编号：{'、'.join(order_tools.list_order_ids())}"],
        }

    row = matched.iloc[0]
    quantity = int(pd.to_numeric(matched["quantity"], errors="coerce").fillna(0).iloc[0])
    deadline = pd.to_datetime(row["deadline"], errors="coerce")

    analysis = evaluate_delivery(
        product=str(row["product"]),
        quantity=quantity,
        deadline=deadline,
        today=today,
    )
    analysis.update(
        {
            "order_id": str(row["order_id"]),
            "priority": str(row["priority"]),
            "order_source": "erp_order",
        }
    )
    return analysis


def analyze_order_request(product, quantity, delivery_days=None, deadline=None, today=None):
    """分析「用户口述的订单」的可交付性（入口 2）。

    参数：
        product:       产品名称（与 MES / 订单中的产品名一致）。
        quantity:      数量。
        delivery_days: 今天起 N 天内交付（与 deadline 二选一）。
        deadline:      具体交付日期（ISO 字符串或日期对象）。
        today:         参考日期，缺省取系统当天（便于测试固定时间）。

    返回 dict：在 ``evaluate_delivery()`` 结果基础上增加
    ``order_source="user_description"``、``matched_orders`` 与 ``delivery_days``。
    """
    if not product or quantity is None:
        return {
            "order_id": None,
            "risk": "unknown",
            "reason": "订单描述缺少产品名称或数量，无法测算",
            "suggestion": "请补充产品与数量，例如：10000 件电机壳体，15 天交付",
            "notes": [],
        }

    quantity = int(quantity)
    reference = _reference_day(today)

    if delivery_days is not None:
        deadline_value = reference + pd.Timedelta(days=int(delivery_days))
    else:
        deadline_value = pd.to_datetime(deadline, errors="coerce")

    notes = ["订单来自用户描述（未提供订单编号），按用户给出的产品/数量/交期单独测算"]

    matched_orders = order_tools.find_matching_orders(product=product, quantity=quantity)
    if matched_orders:
        matched_ids = "、".join(str(item["order_id"]) for item in matched_orders)
        notes.append(
            f"文本描述与在手订单 {matched_ids} 一致（同产品同数量），"
            "已按用户给出的交期单独测算"
        )

    analysis = evaluate_delivery(
        product=str(product),
        quantity=quantity,
        deadline=deadline_value,
        today=today,
        extra_notes=notes,
    )
    analysis.update(
        {
            "order_id": None,
            "order_source": "user_description",
            "delivery_days": None if delivery_days is None else int(delivery_days),
            "matched_orders": matched_orders,
        }
    )
    return analysis


def analyze_orders_overview():
    """无指定订单时的订单总览分析（同样返回 risk / reason / suggestion）。"""
    summary = order_tools.get_order_summary()
    shortage = inventory_tools.get_shortage_list()

    risk = "medium" if shortage else "low"
    reason = (
        f"在手订单 {summary['order_count']} 单，合计 {summary['total_quantity']} 件，"
        f"高优先级 {summary['high_priority_count']} 单，"
        f"交付窗口 {summary['earliest_deadline']} ~ {summary['latest_deadline']}"
    )
    if shortage:
        reason += f"；全厂有 {len(shortage)} 项物料低于安全库存"

    return {
        "risk": risk,
        "reason": reason,
        "suggestion": "按优先级与交期排产，并优先处理物料预警项",
        "order_summary": summary,
        "priority_breakdown": order_tools.get_priority_breakdown_records(),
        "material_summary": inventory_tools.get_inventory_summary(),
    }


def run(capabilities=None, arguments=None):
    """Agent 统一入口。

    参数：
        capabilities: 本次需要的能力列表，如 ["order", "inventory", "production"]。
        arguments:    上下文参数，支持 ``order_id`` / ``order_ids``，
                      或订单描述 ``product`` + ``quantity`` + ``delivery_days`` / ``deadline``。
    """
    capabilities = list(capabilities or ["order"])
    arguments = dict(arguments or {})
    order_ids = [str(value) for value in (arguments.get("order_ids") or [])]
    order_id = arguments.get("order_id") or (order_ids[0] if order_ids else None)

    result = {
        "agent": "order_agent",
        "status": "ok",
        "capabilities": capabilities,
    }

    if order_id:
        analysis = analyze_order_delivery(order_id, today=arguments.get("today"))
    elif arguments.get("product") and arguments.get("quantity"):
        analysis = analyze_order_request(
            product=arguments.get("product"),
            quantity=arguments.get("quantity"),
            delivery_days=arguments.get("delivery_days"),
            deadline=arguments.get("deadline"),
            today=arguments.get("today"),
        )
    else:
        analysis = None

    if analysis is not None:
        result.update(
            {
                "risk": analysis["risk"],
                "reason": analysis["reason"],
                "suggestion": analysis["suggestion"],
                "deliverability": analysis,
            }
        )
    else:
        result.update(analyze_orders_overview())

    if "production" in capabilities:
        result["capacity_summary"] = order_tools.get_factory_capacity()
    if "inventory" in capabilities:
        result["material_summary"] = inventory_tools.get_inventory_summary()

    return result


def main():
    """命令行入口。

    示例：
        python -m agents.order_agent O001
        python -m agents.order_agent --product 电机壳体 --quantity 10000 --days 15
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Order Agent 订单可交付分析")
    parser.add_argument("order_id", nargs="?", help="订单编号，如 O001")
    parser.add_argument("--product", help="产品名称，如 电机壳体")
    parser.add_argument("--quantity", type=int, help="数量")
    parser.add_argument("--days", type=int, help="今天起 N 天内交付")
    parser.add_argument("--deadline", help="交付日期，如 2026-11-01")
    parser.add_argument("--today", help="参考日期（默认系统当天），如 2026-10-11")
    args = parser.parse_args()

    if args.order_id:
        payload = analyze_order_delivery(args.order_id, today=args.today)
    elif args.product and args.quantity:
        payload = analyze_order_request(
            product=args.product,
            quantity=args.quantity,
            delivery_days=args.days,
            deadline=args.deadline,
            today=args.today,
        )
    else:
        payload = analyze_orders_overview()

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
