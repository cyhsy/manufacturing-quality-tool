"""Planning Agent：生产计划编排（S5-A-01）。

输入：订单需求——订单编号，或「产品 + 数量 + 交期」（口述订单）。

调用：

    agents.order_agent              交付能力测算（evaluate_delivery / analyze_order_delivery）
    agent_tools.inventory_tools     库存风险（-> tools.inventory_tool）
    agent_tools.order_tools         当前产能（-> tools.production_tool）
    agents.equipment_agent          设备风险（故障设备、维保、传感器告警）
    agents.quality_agent            在制质量风险（可选，对应 Sprint 5 目标中的「质量风险存在」）
    agent_tools.planning_tools      排产（S5-A-02，内部调用 modules/planning_engine 规则模型）

输出：生产计划——排产方案（日级）、风险清单、可执行建议。

规则模型见 ``modules/planning_engine.py``：优先满足交期 / 避开故障设备 /
优先高风险订单 / 考虑库存。本 Agent 只做编排与风险汇总，不重复实现规则。
"""

import pandas as pd

from agent_tools import inventory_tools, order_tools, planning_tools
from agents import equipment_agent, order_agent, quality_agent
from modules.planning_engine import RISK_ORDER


def _max_risk(*risks):
    """取最严重的风险等级（high > medium > low）。"""
    known = [str(risk) for risk in risks if str(risk) in RISK_ORDER]
    if not known:
        return "unknown"
    return max(known, key=RISK_ORDER.index)


def select_default_order():
    """未指定订单时，取最紧急的在手订单：高优先级优先，其次交付日期最早。"""
    orders = order_tools.get_orders(sort_by_deadline=True)
    if orders.empty:
        return None, []

    records = [
        {
            "order_id": str(row["order_id"]),
            "product": str(row["product"]),
            "quantity": int(pd.to_numeric(pd.Series([row["quantity"]]), errors="coerce").fillna(0).iloc[0]),
            "deadline": str(row["deadline"]),
            "priority": str(row["priority"]).lower(),
        }
        for _, row in orders.iterrows()
    ]

    ranked = sorted(
        records,
        key=lambda item: (0 if item["priority"] == "high" else 1, item["deadline"]),
    )
    return ranked[0], [item["order_id"] for item in ranked]


def _plan_reason(plan, delivery=None, equipment=None, quality=None):
    """把排产结果与各来源风险汇总成一句结论。"""
    timeline = plan["timeline"]
    parts = [
        (
            f"计划总工期 {timeline['total_days']} 天"
            f"（采购备料 {timeline['material_days']} 天 + 生产 {timeline['production_days']} 天）"
        )
    ]

    if timeline["available_days"] is not None:
        parts.append(
            f"交期剩余 {timeline['available_days']} 天"
            + ("，可满足交期" if timeline["feasible"] else f"，超出 {timeline['gap_days']} 天")
        )
    else:
        parts.append("订单缺少有效交付日期")

    bottleneck = plan["capacity"].get("bottleneck")
    stages = plan["capacity"].get("stages") or []
    if stages:
        candidate = min(
            (stage for stage in stages if stage["effective_capacity"] > 0),
            key=lambda stage: stage["effective_capacity"],
            default=None,
        )
        if candidate is not None:
            parts.append(
                f"瓶颈工序 {candidate['process']}"
                f"（{candidate['equipment']}，{candidate['effective_capacity']} 件/天）"
            )
    elif bottleneck is None:
        parts.append("该产品在 MES 中没有对应产线")

    shortages = plan["material"].get("shortage_materials") or []
    if shortages:
        parts.append("物料缺口：" + "、".join(shortages))

    blocked = [
        stage for stage in stages if stage.get("blocked")
    ]
    if blocked:
        parts.append(
            "受阻工序："
            + "、".join(f"{stage['process']}/{stage['original_equipment']}" for stage in blocked)
        )

    if delivery and delivery.get("risk"):
        parts.append(f"订单交付基准风险 {delivery['risk']}")
    if equipment and equipment.get("risk"):
        parts.append(f"设备风险 {equipment['risk']}")
    if quality and quality.get("risk"):
        parts.append(f"质量风险 {quality['risk']}")

    return "；".join(parts)


def build_plan(
    order_id=None,
    product=None,
    quantity=None,
    delivery_days=None,
    deadline=None,
    today=None,
    priority=None,
    include_equipment=True,
    include_quality=True,
):
    """生成生产计划 + 风险视图（S5-A-01 主入口）。

    参数：
        order_id:         订单编号；缺省且未给产品/数量时，自动取最紧急在手订单。
        product/quantity: 口述订单（无订单编号时使用）。
        delivery_days:    今天起 N 天内交付。
        deadline:         交付日期。
        today:            参考日期，缺省系统当天。
        priority:         优先级；缺省取订单优先级。
        include_equipment: 是否调用设备 Agent 汇总设备风险。
        include_quality:   是否调用质量 Agent 汇总在制质量风险。

    返回 dict：risk / reason / suggestion + plan（排产）+ 各来源风险 + sources。
    """
    reference = (
        pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.today().normalize()
    )

    assumptions = []
    candidate_order_ids = []

    # 给了产品/数量但不完整：明确要求补齐，避免静默改用其它订单
    incomplete_request = bool(product) or quantity is not None
    if order_id is None and incomplete_request and not (product and quantity is not None):
        return {
            "agent": "planning_agent",
            "status": "ok",
            "risk": "unknown",
            "reason": "缺少产品与数量（或有效的订单编号），无法排产",
            "suggestion": (
                "请补充产品名称与数量（例如：10000 件电机壳体，15 天交付），或直接给出订单编号"
            ),
            "plan": None,
            "sources": {"planning_tools": "agent_tools.planning_tools.generate_production_plan()"},
        }

    if order_id is None and not incomplete_request:
        default_order, candidate_order_ids = select_default_order()
        if default_order is None:
            return {
                "agent": "planning_agent",
                "status": "ok",
                "risk": "unknown",
                "reason": "没有可排产的订单或产品需求",
                "suggestion": "请提供订单编号，或给出产品与数量（例如：10000 件电机壳体，15 天交付）",
                "plan": None,
                "sources": {"planning_tools": "agent_tools.planning_tools.generate_production_plan()"},
            }
        order_id = default_order["order_id"]
        assumptions.append(
            f"未指定订单，按最紧急的在手订单 {order_id}"
            f"（{default_order['product']} {default_order['quantity']} 件，"
            f"{default_order['deadline']} 交付）生成计划"
        )

    # 1）设备风险（agents.equipment_agent）
    equipment_result = None
    if include_equipment:
        equipment_result = equipment_agent.run(
            capabilities=["equipment"], arguments={"today": today}
        )

    # 2）在制质量风险（agents.quality_agent，可选）
    quality_risk = None
    quality_result = None
    if include_quality:
        quality_result = quality_agent.run(capabilities=["quality"])
        quality_risk = {"risk": quality_result.get("risk"), "reason": quality_result.get("reason")}

    # 3）排产（agent_tools.planning_tools -> modules/planning_engine）
    plan = planning_tools.generate_production_plan(
        order_id=order_id,
        product=product,
        quantity=quantity,
        delivery_days=delivery_days,
        deadline=deadline,
        today=today,
        priority=priority,
        quality_risk=quality_risk,
    )

    if plan.get("status") == "error":
        return {
            "agent": "planning_agent",
            "status": "ok",
            "risk": "unknown",
            "reason": plan.get("reason"),
            "suggestion": plan.get("suggestion"),
            "plan": plan,
            "sources": plan.get("sources", {}),
        }

    # 4）库存风险（agent_tools.inventory_tools）
    inventory_summary = inventory_tools.get_inventory_summary()

    # 5）交付能力基准（agents.order_agent）
    resolved_order_id = plan.get("order_id")
    if resolved_order_id:
        delivery = order_agent.analyze_order_delivery(resolved_order_id, today=reference)
    else:
        delivery = order_agent.evaluate_delivery(
            product=plan["product"],
            quantity=plan["quantity"],
            deadline=pd.to_datetime(plan.get("deadline"), errors="coerce"),
            today=reference,
        )

    plan_risk = _max_risk(
        *[
            str(item.get("level"))
            for item in plan["risks"]
            if str(item.get("level")) in RISK_ORDER
        ]
    )
    if plan_risk == "unknown":
        plan_risk = "low"

    overall_risk = _max_risk(
        plan_risk,
        delivery.get("risk"),
        (equipment_result or {}).get("risk"),
        (quality_result or {}).get("risk"),
    )

    if plan["status"] == "blocked":
        suggestion = "；".join(plan["suggestions"][:2]) or "确认产线与设备可用状态后重新排产"
    elif plan["timeline"]["feasible"]:
        suggestion = plan["suggestions"][-1] if plan["suggestions"] else "按计划执行"
        suggestion = "；".join(plan["suggestions"][:2])
    else:
        suggestion = "；".join(plan["suggestions"][:3])

    return {
        "agent": "planning_agent",
        "status": "ok",
        "risk": overall_risk,
        "reason": _plan_reason(plan, delivery, equipment_result, quality_result),
        "suggestion": suggestion,
        "assumptions": assumptions,
        "candidate_order_ids": candidate_order_ids,
        "plan_status": plan["status"],
        "request": {
            "order_id": resolved_order_id,
            "product": plan["product"],
            "quantity": plan["quantity"],
            "priority": plan["priority"],
            "deadline": plan.get("deadline"),
            "today": plan["timeline"]["today"],
        },
        "plan": plan,
        "plan_lines": plan["plan_lines"],
        "risks": plan["risks"],
        "suggestions": plan["suggestions"],
        "delivery_baseline": {
            "risk": delivery.get("risk"),
            "reason": delivery.get("reason"),
            "suggestion": delivery.get("suggestion"),
            "required_days": delivery.get("required_days"),
            "available_days": delivery.get("available_days"),
        },
        "inventory_risk": inventory_summary,
        "equipment_risk": (
            {
                "risk": equipment_result.get("risk"),
                "reason": equipment_result.get("reason"),
                "abnormal_count": equipment_result.get("equipment_summary", {}).get("abnormal_count"),
            }
            if equipment_result
            else None
        ),
        "quality_risk": (
            {
                "risk": quality_result.get("risk"),
                "reason": quality_result.get("reason"),
                "total_defects": quality_result.get("metrics", {}).get("total_defects"),
            }
            if quality_result
            else None
        ),
        "sources": plan.get("sources", {}),
    }


def run(capabilities=None, arguments=None):
    """Agent 统一入口（production_planning）。"""
    capabilities = list(capabilities or ["production_planning"])
    arguments = dict(arguments or {})

    result = build_plan(
        order_id=arguments.get("order_id"),
        product=arguments.get("product"),
        quantity=arguments.get("quantity"),
        delivery_days=arguments.get("delivery_days"),
        deadline=arguments.get("deadline"),
        today=arguments.get("today"),
        priority=arguments.get("priority"),
    )
    result["capabilities"] = capabilities
    return result


def main():
    """命令行入口。

    示例：
        python -m agents.planning_agent                                  # 最紧急在手订单
        python -m agents.planning_agent O009
        python -m agents.planning_agent --product 电机壳体 --quantity 10000 --days 15
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Planning Agent 生产计划编排")
    parser.add_argument("order_id", nargs="?", help="订单编号，如 O001")
    parser.add_argument("--product", help="产品名称，如 电机壳体")
    parser.add_argument("--quantity", type=int, help="数量")
    parser.add_argument("--days", type=int, help="今天起 N 天内交付")
    parser.add_argument("--deadline", help="交付日期，如 2026-11-01")
    parser.add_argument("--priority", help="优先级：high / normal / low")
    parser.add_argument("--today", help="参考日期，如 2026-10-11")
    parser.add_argument("--no-quality", action="store_true", help="不调用质量 Agent")
    args = parser.parse_args()

    payload = build_plan(
        order_id=args.order_id,
        product=args.product,
        quantity=args.quantity,
        delivery_days=args.days,
        deadline=args.deadline,
        today=args.today,
        priority=args.priority,
        include_quality=not args.no_quality,
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
