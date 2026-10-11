"""成本模型（S6-A-03 的模型层）。

简单模型（v1 经验值，全部集中在常量里，便于按实际财务口径调整）：

========================  ==========================================================
成本项                     口径
========================  ==========================================================
加急采购成本               物料缺口金额 × 加急费率（默认 8%）
加班成本                   参与加班工序数 × 优化后生产工期 × 单工序日加班成本
换线调试成本               启用替代设备台数 × 单台换线成本
延期成本                   延期天数 ×（合同违约金 + 间接损失）
========================  ==========================================================

说明：

- 物料单价为 v1 经验值（元/kg），未接入真实采购价；
- 延期损失拆成「违约金」与「间接损失」（客户关系、加急物流、信誉）两部分，
  只认合同罚金时把 ``DELAY_INDIRECT_COST_PER_DAY`` 调为 0 即可；
- 本模块只做算术，不做决策；决策口径见 ``modules/decision_engine.py``。
  Agent 侧调用入口为 ``agent_tools/cost_tools.py``。
"""


# 物料单价（元/kg，v1 经验值）
MATERIAL_UNIT_PRICE = {
    "铝合金": 22.0,
    "钢材": 6.5,
    "铸铁": 5.2,
    "铜材": 68.0,
    "轴承钢": 12.0,
    "不锈钢棒料": 26.0,
    "切削液": 18.0,
    "防锈油": 24.0,
    "焊丝": 32.0,
    "砂轮": 45.0,
    "刀具": 260.0,
    "密封圈": 1.2,
    "包装箱": 8.0,
}
DEFAULT_MATERIAL_PRICE = 20.0

EXPEDITE_FEE_RATE = 0.08

SHIFT_STAGE_DAILY_COST = 1000.0
EQUIPMENT_SETUP_COST = 3000.0

DELAY_PENALTY_PER_DAY = 12000.0
DELAY_INDIRECT_COST_PER_DAY = 25000.0

CURRENCY = "元"

COST_MEASURE_EXPRESS = "express_purchase"
COST_MEASURE_EQUIPMENT = "enable_equipment"
COST_MEASURE_SHIFT = "shift"


def material_unit_price(material):
    """物料单价（元/kg）。"""
    return float(MATERIAL_UNIT_PRICE.get(str(material), DEFAULT_MATERIAL_PRICE))


def expedite_purchase_cost(material_requirements):
    """加急采购成本：仅对存在缺口的物料计费。

    参数：
        material_requirements: ``[{material, shortage, unit}, ...]``

    返回：
        ``{"amount", "items", "rate"}``
    """
    items = []
    for requirement in material_requirements or []:
        shortage = float(requirement.get("shortage") or 0)
        if shortage <= 0:
            continue

        material = str(requirement.get("material"))
        unit_price = material_unit_price(material)
        value = shortage * unit_price
        items.append(
            {
                "cost_item": f"加急采购费（{material}）",
                "material": material,
                "shortage": shortage,
                "unit": str(requirement.get("unit", "")),
                "unit_price": unit_price,
                "material_value": round(value, 2),
                "amount": round(value * EXPEDITE_FEE_RATE, 2),
                "detail": (
                    f"缺口 {shortage:g}{requirement.get('unit', '')} × "
                    f"{unit_price:g} 元 × 加急费率 {EXPEDITE_FEE_RATE:.0%}"
                ),
            }
        )

    return {
        "amount": round(sum(item["amount"] for item in items), 2),
        "items": items,
        "rate": EXPEDITE_FEE_RATE,
    }


def overtime_cost(stage_count, production_days):
    """加班成本：参与加班的工序数 × 优化后生产工期 × 单工序日加班成本。"""
    stage_count = int(stage_count or 0)
    production_days = int(production_days or 0)
    amount = round(stage_count * production_days * SHIFT_STAGE_DAILY_COST, 2)

    return {
        "amount": amount,
        "items": [
            {
                "cost_item": "加班成本",
                "stage_count": stage_count,
                "production_days": production_days,
                "unit_cost": SHIFT_STAGE_DAILY_COST,
                "amount": amount,
                "detail": (
                    f"{stage_count} 道工序 × {production_days} 天 × "
                    f"{SHIFT_STAGE_DAILY_COST:g} 元/工序·天"
                ),
            }
        ],
    }


def equipment_setup_cost(equipment_count):
    """换线调试成本：启用替代设备台数 × 单台换线成本。"""
    equipment_count = int(equipment_count or 0)
    amount = round(equipment_count * EQUIPMENT_SETUP_COST, 2)

    return {
        "amount": amount,
        "items": [
            {
                "cost_item": "换线调试成本",
                "equipment_count": equipment_count,
                "unit_cost": EQUIPMENT_SETUP_COST,
                "amount": amount,
                "detail": f"{equipment_count} 台 × {EQUIPMENT_SETUP_COST:g} 元/台",
            }
        ],
    }


def delay_cost(days):
    """延期成本：延期天数 ×（合同违约金 + 间接损失）。"""
    days = max(int(days or 0), 0)
    per_day = DELAY_PENALTY_PER_DAY + DELAY_INDIRECT_COST_PER_DAY
    amount = round(days * per_day, 2)

    return {
        "amount": amount,
        "days": days,
        "per_day": per_day,
        "penalty_per_day": DELAY_PENALTY_PER_DAY,
        "indirect_per_day": DELAY_INDIRECT_COST_PER_DAY,
        "items": [
            {
                "cost_item": "延期损失",
                "days": days,
                "unit_cost": per_day,
                "amount": amount,
                "detail": (
                    f"{days} 天 ×（违约金 {DELAY_PENALTY_PER_DAY:g} + "
                    f"间接损失 {DELAY_INDIRECT_COST_PER_DAY:g}）元/天"
                ),
            }
        ],
    }


def summarize_cost(groups):
    """汇总成本明细：``{"increase", "breakdown", "currency"}``。"""
    breakdown = []
    for group in groups or []:
        breakdown.extend(group.get("items") or [])

    return {
        "increase": round(sum(item["amount"] for item in breakdown), 2),
        "breakdown": breakdown,
        "currency": CURRENCY,
    }


def evaluate_optimization_cost(
    measures,
    material_requirements=None,
    optimized_production_days=None,
    baseline_delay_days=0,
    optimized_delay_days=0,
):
    """汇总优化方案的成本增量与收益。

    参数：
        measures: 实际执行的措施列表，元素含 ``type``
                  （``express_purchase`` / ``enable_equipment`` / ``shift``）。
        material_requirements: 物料需求（用于加急采购成本）。
        optimized_production_days: 优化后的生产工期（用于加班成本）。
        baseline_delay_days: 原计划的延期天数（收益基准）。
        optimized_delay_days: 优化后的延期天数。

    返回：
        ``{"increase", "breakdown", "benefit", "net", "currency"}``
    """
    groups = []
    applied_types = {str(measure.get("type")) for measure in measures or []}

    if COST_MEASURE_EXPRESS in applied_types:
        groups.append(expedite_purchase_cost(material_requirements or []))

    if COST_MEASURE_EQUIPMENT in applied_types:
        equipment_count = sum(
            len(measure.get("equipments") or [measure.get("equipment")])
            for measure in measures or []
            if str(measure.get("type")) == COST_MEASURE_EQUIPMENT
        )
        groups.append(equipment_setup_cost(equipment_count))

    if COST_MEASURE_SHIFT in applied_types:
        stage_count = sum(
            int(measure.get("stage_count") or 0)
            for measure in measures or []
            if str(measure.get("type")) == COST_MEASURE_SHIFT
        )
        groups.append(overtime_cost(stage_count, optimized_production_days or 0))

    cost = summarize_cost(groups)

    delay_saved = max(int(baseline_delay_days or 0) - int(optimized_delay_days or 0), 0)
    avoided = delay_cost(delay_saved)
    remaining = delay_cost(optimized_delay_days)

    benefit = {
        "avoided_delay_days": delay_saved,
        "avoided_amount": avoided["amount"],
        "remaining_delay_days": int(optimized_delay_days or 0),
        "remaining_amount": remaining["amount"],
        "detail": avoided["items"][0]["detail"] if avoided["items"] else None,
    }

    return {
        "increase": cost["increase"],
        "breakdown": cost["breakdown"],
        "benefit": benefit,
        "net": round(benefit["avoided_amount"] - cost["increase"], 2),
        "currency": CURRENCY,
    }
