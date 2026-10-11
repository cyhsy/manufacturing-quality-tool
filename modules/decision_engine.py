"""决策融合层（S6-A-02）。

输入：

- 订单风险（``agents.order_agent``）
- 质量风险（``agents.quality_agent``）
- 设备风险（``agents.equipment_agent``）
- 排产方案（``modules.planning_engine``）

输出：综合建议——基线方案、候选优化措施（**逐步节省天数**）、预计工期、
成本增量与收益、风险画像与推荐结论。

措施评估方式（可复现、可解释）：

1. 候选措施按固定顺序生成：**加急采购 → 启用替代/并行设备 → 增加班次**；
2. **逐项累加**评估：某项措施的节省 = 上一场景总工期 − 加入该措施后的总工期；
3. 无节省的措施标记为「无额外收益」并从后续场景中剔除；
4. 工期模拟复用 ``modules.planning_engine.simulate_scenario()``，
   成本口径复用 ``modules.cost_model.py``（Agent 侧入口 ``agent_tools/cost_tools.py``）。

推荐结论：

===========  ====================================================
decision     含义
===========  ====================================================
execute      优化后可满足交期，且净收益 ≥ 0
trade_off    优化后可满足交期，但成本高于避免的延期损失（需权衡）
escalate     优化后仍无法满足交期（需外协或协商交期）
keep_plan    原计划已满足交期，无需优化
===========  ====================================================
"""

from modules import cost_model, planning_engine


DECISION_EXECUTE = "execute"
DECISION_TRADE_OFF = "trade_off"
DECISION_ESCALATE = "escalate"
DECISION_KEEP = "keep_plan"

DECISION_LABELS = {
    DECISION_EXECUTE: "建议执行",
    DECISION_TRADE_OFF: "建议执行（需权衡成本）",
    DECISION_ESCALATE: "需升级处理",
    DECISION_KEEP: "按原计划执行",
}

RISK_ORDER = planning_engine.RISK_ORDER


def _timeline(plan):
    return (plan or {}).get("timeline") or {}


def _stages(plan):
    return ((plan or {}).get("capacity") or {}).get("stages") or []


def _material(plan):
    return (plan or {}).get("material") or {}


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def bottleneck_stage(stages):
    """瓶颈工序：有效日产能最小的可开工工序。"""
    candidates = [
        stage for stage in stages or [] if _to_int(stage.get("effective_capacity")) > 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda stage: _to_int(stage["effective_capacity"]))


def build_measures(plan):
    """生成候选优化措施（按固定顺序，仅给出可实施的）。"""
    material = _material(plan)
    stages = _stages(plan)

    measures = []

    if material.get("shortage_materials") and not material.get("express"):
        measures.append(
            {
                "type": cost_model.COST_MEASURE_EXPRESS,
                "name": (
                    f"加急采购（{'、'.join(material['shortage_materials'])}，"
                    f"{_to_int(material.get('purchase_days'))} 天 → "
                    f"{planning_engine.PURCHASE_LEAD_DAYS_EXPRESS} 天）"
                ),
                "materials": list(material["shortage_materials"]),
            }
        )

    bottleneck = bottleneck_stage(stages)
    if bottleneck is not None:
        usable = bottleneck.get("usable_alternatives") or []
        if usable:
            measures.append(
                {
                    "type": cost_model.COST_MEASURE_EQUIPMENT,
                    "name": (
                        f"启用 {bottleneck['process']} 并行设备"
                        f"（{'、'.join(item['equipment'] for item in usable)}）"
                    ),
                    "process": bottleneck["process"],
                    "equipments": [item["equipment"] for item in usable],
                    "capacity": sum(_to_int(item["daily_capacity"]) for item in usable),
                    "adds_capacity": (
                        f"{_to_int(bottleneck['effective_capacity'])} → "
                        f"{_to_int(bottleneck['effective_capacity']) + sum(_to_int(item['daily_capacity']) for item in usable)}"
                        " 件/天"
                    ),
                }
            )

    if stages:
        measures.append(
            {
                "type": cost_model.COST_MEASURE_SHIFT,
                "name": (
                    f"关键工序增加班次（产能 +{int(planning_engine.SHIFT_BOOST_RATIO * 100)}%）"
                ),
                "ratio": planning_engine.SHIFT_BOOST_RATIO,
                "stage_count": len(
                    [stage for stage in stages if _to_int(stage.get("effective_capacity")) > 0]
                ),
            }
        )

    return measures


def evaluate_measures(plan, measures=None):
    """逐项累加评估措施，返回 (明细行, 实际采纳措施, 优化后总工期)。

    返回的明细行包含 ``days_saved``（相对上一场景的节省天数）、
    ``total_days_after``（累计后的总工期）与 ``applicable``（是否有效）。
    """
    stages = _stages(plan)
    quantity = _to_int((plan or {}).get("quantity"))
    timeline = _timeline(plan)
    material_days = _to_int(timeline.get("material_days"))
    previous_total = timeline.get("total_days")

    candidates = list(build_measures(plan) if measures is None else measures)

    rows = []
    applied = []

    for measure in candidates:
        trial = applied + [measure]
        scenario = planning_engine.simulate_scenario(
            stages, quantity, material_days, trial
        )
        current_total = scenario["total_days"]

        saved = 0
        if previous_total is not None and current_total is not None:
            saved = max(int(previous_total) - int(current_total), 0)

        if saved <= 0:
            rows.append(
                {
                    **measure,
                    "days_saved": 0,
                    "total_days_after": previous_total,
                    "applicable": False,
                    "note": "无额外收益",
                }
            )
            continue

        applied.append(measure)
        rows.append(
            {
                **measure,
                "days_saved": saved,
                "total_days_after": current_total,
                "production_days_after": scenario["production_days"],
                "applicable": True,
                "note": None,
            }
        )
        previous_total = current_total

    return rows, applied, previous_total


def assess_risks(plan, order_risk=None, quality_risk=None, equipment_risk=None):
    """融合订单 / 质量 / 设备 / 计划四类风险，并给出提示。"""
    plan_risk = planning_engine.max_risk((plan or {}).get("risks"))

    risk_profile = {
        "order": {
            "risk": (order_risk or {}).get("risk"),
            "reason": (order_risk or {}).get("reason"),
        },
        "quality": {
            "risk": (quality_risk or {}).get("risk"),
            "reason": (quality_risk or {}).get("reason"),
        },
        "equipment": {
            "risk": (equipment_risk or {}).get("risk"),
            "reason": (equipment_risk or {}).get("reason"),
        },
        "plan": {
            "risk": plan_risk,
            "reason": "；".join(
                item["item"]
                for item in (plan or {}).get("risks") or []
                if item.get("level") == "high"
            )
            or "计划无高风险项",
        },
    }

    levels = [
        value["risk"] for value in risk_profile.values() if value["risk"] in RISK_ORDER
    ]
    risk_profile["overall"] = max(levels, key=RISK_ORDER.index) if levels else "low"

    notes = []
    timeline = _timeline(plan)
    if timeline.get("feasible") is False:
        notes.append(
            f"计划工期 {timeline.get('total_days')} 天超出交期剩余 "
            f"{timeline.get('available_days')} 天，交期存在延期风险"
        )
    if risk_profile["equipment"]["risk"] == "high":
        notes.append(
            "设备风险 high：计划按当前在产产能测算，未包含新的设备故障；建议同步执行设备维保"
        )
    if risk_profile["quality"]["risk"] == "high":
        notes.append(
            "质量风险 high：建议在关键工序增加首件检验，避免返工进一步消耗产能"
        )
    if risk_profile["order"]["risk"] == "high":
        notes.append("订单交付风险 high：建议按优化方案执行并每日跟踪进度")

    risk_profile["notes"] = notes
    return risk_profile


def build_recommendation(timeline, optimized_total, optimized_delay, cost, applied, risks):
    """生成推荐结论与行动项。"""
    available = timeline.get("available_days")
    baseline_feasible = bool(timeline.get("feasible"))
    optimized_feasible = (
        optimized_total is not None
        and available is not None
        and int(optimized_total) <= int(available)
    )

    if baseline_feasible:
        decision = DECISION_KEEP
    elif not applied:
        decision = DECISION_ESCALATE
    elif optimized_feasible:
        decision = DECISION_EXECUTE if cost.get("net", 0) >= 0 else DECISION_TRADE_OFF
    else:
        decision = DECISION_ESCALATE

    reasons = []
    actions = []
    slack = (
        int(available) - int(timeline.get("total_days"))
        if available is not None and timeline.get("total_days") is not None
        else None
    )

    if baseline_feasible:
        reasons.append(
            f"原计划 {timeline.get('total_days')} 天满足交期 {available} 天"
            + (f"（缓冲 {slack} 天）" if slack is not None else "")
            + "，无需优化"
        )
    else:
        reasons.append(
            f"原计划 {timeline.get('total_days')} 天超出交期 "
            f"{available} 天（缺口 {timeline.get('gap_days')} 天）"
        )

    if applied:
        saved_total = (
            int(timeline.get("total_days")) - int(optimized_total)
            if timeline.get("total_days") is not None and optimized_total is not None
            else 0
        )
        if baseline_feasible:
            reasons.append(
                f"可选优化：执行 {len(applied)} 项措施后总工期 {optimized_total} 天"
                f"（缩短 {saved_total} 天），成本增加 {cost.get('increase', 0):g} 元，"
                "无延期损失可避免，仅在需要提升交付缓冲或释放产能时考虑"
            )
        else:
            reasons.append(
                f"执行 {len(applied)} 项措施后总工期 {optimized_total} 天"
                f"（节省 {saved_total} 天），"
                + ("可满足交期" if optimized_feasible else f"仍超出 {optimized_delay} 天")
            )
            reasons.append(
                f"成本增加 {cost.get('increase', 0):g} 元，避免延期损失 "
                f"{cost.get('benefit', {}).get('avoided_amount', 0):g} 元，"
                f"净收益 {cost.get('net', 0):g} 元"
            )
            if decision == DECISION_TRADE_OFF:
                reasons.append("成本高于避免的延期损失，需权衡交付承诺与成本")

        prefix = "（可选）" if baseline_feasible else ""
        actions.extend(
            f"{prefix}执行措施 {index}：{measure['name']}"
            for index, measure in enumerate(applied, start=1)
        )
    else:
        actions.append("确认产线、设备与物料状态后重新排产")

    if not optimized_feasible and not baseline_feasible:
        actions.append("安排外协加工或与客户协商交期/拆分批次")
    if risks.get("equipment", {}).get("risk") == "high":
        actions.append("同步执行设备维保（设备风险 high）")
    if risks.get("quality", {}).get("risk") == "high":
        actions.append("关键工序增加首件检验（质量风险 high）")

    return {
        "decision": decision,
        "label": DECISION_LABELS[decision],
        "reason": "；".join(reasons),
        "actions": actions,
        "baseline_feasible": baseline_feasible,
        "optimized_feasible": optimized_feasible,
    }


def build_decision(plan, order_risk=None, quality_risk=None, equipment_risk=None):
    """决策融合主入口。

    参数：
        plan:           ``modules.planning_engine.build_production_plan()`` 的结果。
        order_risk:     订单风险（``agents.order_agent`` 的结果）。
        quality_risk:   质量风险（``agents.quality_agent`` 的结果）。
        equipment_risk: 设备风险（``agents.equipment_agent`` 的结果）。

    返回 dict：order / baseline / measures / optimized / cost / risks / recommendation。
    """
    timeline = _timeline(plan)
    quantity = _to_int((plan or {}).get("quantity"))

    rows, applied, optimized_total = evaluate_measures(plan)

    baseline_delay = max(_to_int(timeline.get("gap_days")), 0)
    available = timeline.get("available_days")
    optimized_delay = baseline_delay
    if optimized_total is not None and available is not None:
        optimized_delay = max(int(optimized_total) - int(available), 0)

    optimized_production_days = timeline.get("production_days")
    for row in rows:
        if row["applicable"]:
            optimized_production_days = row.get("production_days_after")

    cost = cost_model.evaluate_optimization_cost(
        applied,
        material_requirements=_material(plan).get("requirements"),
        optimized_production_days=optimized_production_days,
        baseline_delay_days=baseline_delay,
        optimized_delay_days=optimized_delay,
    )

    risks = assess_risks(plan, order_risk, quality_risk, equipment_risk)
    recommendation = build_recommendation(
        timeline, optimized_total, optimized_delay, cost, applied, risks
    )

    optimized_feasible = (
        optimized_total is not None
        and available is not None
        and int(optimized_total) <= int(available)
    )

    return {
        "order": {
            "order_id": (plan or {}).get("order_id"),
            "product": (plan or {}).get("product"),
            "quantity": quantity,
            "deadline": (plan or {}).get("deadline"),
            "priority": (plan or {}).get("priority"),
        },
        "baseline": {
            "total_days": timeline.get("total_days"),
            "production_days": timeline.get("production_days"),
            "material_days": timeline.get("material_days"),
            "serial_days": timeline.get("serial_days"),
            "available_days": available,
            "feasible": timeline.get("feasible"),
            "gap_days": timeline.get("gap_days"),
        },
        "measures": rows,
        "optimized": {
            "total_days": optimized_total,
            "production_days": optimized_production_days,
            "available_days": available,
            "feasible": optimized_feasible,
            "days_saved": (
                _to_int(timeline.get("total_days")) - int(optimized_total)
                if optimized_total is not None and timeline.get("total_days") is not None
                else None
            ),
            "delay_days": optimized_delay,
        },
        "cost": cost,
        "risks": risks,
        "recommendation": recommendation,
        "plan_lines": (plan or {}).get("plan_lines"),
        "plan_status": (plan or {}).get("status"),
    }
