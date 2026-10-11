"""制造决策报告（S6-A-04）：把决策结果渲染成 Markdown 并写入 ``reports/``。

报告结构：

    一、当前方案    计划工期 / 交期剩余 / 结论 / 瓶颈工序 / 排产明细
    二、风险        订单 / 质量 / 设备 / 计划 四维风险与提示
    三、优化方案    逐项措施、节省天数、累计工期、成本
    四、预计        优化后工期、成本增加（含明细）、收益、净收益
    五、综合建议    建议等级、理由、行动项
    六、数据来源    取数链路与成本费率口径

文件名按「订单（或产品）+ 计划基准日期」生成，重复运行会**覆盖**同一文件，
避免 reports/ 目录堆积时间戳文件。
"""

from datetime import datetime
from pathlib import Path

from modules import cost_model


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"

RISK_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "unknown": "未知",
    None: "未评估",
}

DIMENSION_LABELS = {
    "order": "订单交付",
    "quality": "质量",
    "equipment": "设备",
    "plan": "生产计划",
}


def _risk_text(level):
    label = RISK_LABELS.get(level, str(level))
    return f"{label}（{level}）" if level in RISK_LABELS and level else label


def _money(value):
    try:
        return f"{float(value):,.0f} 元"
    except (TypeError, ValueError):
        return "-"


def report_file_name(decision, reference_date=None):
    """报告文件名：manufacturing_decision_<订单或产品>_<YYYYMMDD>.md。"""
    order = (decision or {}).get("order") or {}
    key = order.get("order_id") or order.get("product") or "unknown"
    key = str(key).replace("/", "-").replace("\\", "-").replace(" ", "")
    stamp = str(reference_date or datetime.now().date().isoformat()).replace("-", "")[:8]
    return f"manufacturing_decision_{key}_{stamp}.md"


def render_decision_report(decision, context=None):
    """把决策结果渲染成 Markdown 文本。"""
    context = dict(context or {})
    order = (decision or {}).get("order") or {}
    baseline = (decision or {}).get("baseline") or {}
    optimized = (decision or {}).get("optimized") or {}
    cost = (decision or {}).get("cost") or {}
    risks = (decision or {}).get("risks") or {}
    recommendation = (decision or {}).get("recommendation") or {}
    measures = (decision or {}).get("measures") or []

    lines = ["# 制造决策报告", ""]

    generated_at = context.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"- 生成时间：{generated_at}")
    if context.get("user_input"):
        lines.append(f"- 用户输入：{context['user_input']}")

    order_bits = []
    if order.get("order_id"):
        order_bits.append(str(order["order_id"]))
    if order.get("product"):
        order_bits.append(str(order["product"]))
    if order.get("quantity") is not None:
        order_bits.append(f"{order['quantity']} 件")
    if order.get("deadline"):
        order_bits.append(f"{order['deadline']} 交付")
    if order.get("priority"):
        order_bits.append(f"优先级 {order['priority']}")
    lines.append(f"- 订单：{' / '.join(order_bits) if order_bits else '（口述订单，无订单编号）'}")
    if context.get("assumptions"):
        for assumption in context["assumptions"]:
            lines.append(f"- 说明：{assumption}")
    lines.append("")

    # 一、当前方案
    lines.append("## 一、当前方案")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append(
        f"| 计划工期 | {baseline.get('total_days')} 天"
        f"（采购备料 {baseline.get('material_days')} 天 + 生产 {baseline.get('production_days')} 天） |"
    )
    lines.append(f"| 交期剩余 | {baseline.get('available_days')} 天 |")
    feasible_text = "✅ 可满足交期" if baseline.get("feasible") else "❌ 无法满足交期"
    if baseline.get("feasible") is False and baseline.get("gap_days") is not None:
        feasible_text += f"（超出 {baseline['gap_days']} 天）"
    lines.append(f"| 结论 | {feasible_text} |")
    if baseline.get("serial_days") is not None:
        lines.append(f"| 串行工期（上限参照） | {baseline['serial_days']} 天 |")
    lines.append("")

    bottleneck = None
    for row in measures:
        if row.get("adds_capacity"):
            bottleneck = row.get("process")
            break
    if bottleneck:
        lines.append(f"- 瓶颈工序：{bottleneck}")
        lines.append("")

    plan_lines = (decision or {}).get("plan_lines") or []
    if plan_lines:
        lines.append("排产明细：")
        lines.append("")
        for item in plan_lines:
            lines.append(f"- {item}")
        lines.append("")

    # 二、风险
    lines.append("## 二、风险")
    lines.append("")
    lines.append("| 维度 | 等级 | 说明 |")
    lines.append("| --- | --- | --- |")
    for key, label in DIMENSION_LABELS.items():
        entry = risks.get(key) or {}
        reason = str(entry.get("reason") or "-").replace("|", "/")
        lines.append(f"| {label} | {_risk_text(entry.get('risk'))} | {reason} |")
    lines.append(f"| **综合** | **{_risk_text(risks.get('overall'))}** | — |")
    lines.append("")
    for note in risks.get("notes") or []:
        lines.append(f"- {note}")
    if risks.get("notes"):
        lines.append("")

    # 三、优化方案
    lines.append("## 三、优化方案")
    lines.append("")
    applicable = [row for row in measures if row.get("applicable")]
    if applicable:
        lines.append("| # | 措施 | 节省 | 累计工期 | 成本 |")
        lines.append("| --- | --- | --- | --- | --- |")
        cost_by_type = {}
        for item in cost.get("breakdown") or []:
            cost_by_type.setdefault(item["cost_item"], 0)
            cost_by_type[item["cost_item"]] += item["amount"]

        for index, row in enumerate(applicable, start=1):
            amount = "-"
            if row["type"] == cost_model.COST_MEASURE_EXPRESS and "加急采购费" in " ".join(cost_by_type):
                amount = _money(
                    sum(
                        value
                        for key, value in cost_by_type.items()
                        if key.startswith("加急采购费")
                    )
                )
            elif row["type"] == cost_model.COST_MEASURE_EQUIPMENT:
                amount = _money(cost_by_type.get("换线调试成本"))
            elif row["type"] == cost_model.COST_MEASURE_SHIFT:
                amount = _money(cost_by_type.get("加班成本"))

            lines.append(
                f"| {index} | {row['name']} | {row['days_saved']} 天 | "
                f"{row['total_days_after']} 天 | {amount} |"
            )
        lines.append("")

        skipped = [row for row in measures if not row.get("applicable")]
        for row in skipped:
            lines.append(f"- 未采纳：{row['name']}（{row.get('note')}）")
        if skipped:
            lines.append("")
    else:
        lines.append("当前无可用优化措施。")
        lines.append("")

    # 四、预计
    lines.append("## 四、预计")
    lines.append("")
    if optimized.get("total_days") is not None:
        lines.append(
            f"- 优化后工期：**{optimized['total_days']} 天**"
            f"（节省 {optimized.get('days_saved')} 天）；"
            + (
                f"可满足交期 {optimized.get('available_days')} 天"
                if optimized.get("feasible")
                else f"仍超出 {optimized.get('delay_days')} 天"
            )
        )
    lines.append(f"- 成本增加：**{_money(cost.get('increase'))}**")
    benefit = cost.get("benefit") or {}
    lines.append(
        f"- 收益：避免延期 {benefit.get('avoided_delay_days', 0)} 天，"
        f"避免延期损失 {_money(benefit.get('avoided_amount'))}"
    )
    lines.append(f"- 净收益：{_money(cost.get('net'))}")
    lines.append("")

    if cost.get("breakdown"):
        lines.append("成本明细：")
        lines.append("")
        lines.append("| 成本项 | 金额 | 口径 |")
        lines.append("| --- | --- | --- |")
        for item in cost["breakdown"]:
            lines.append(
                f"| {item['cost_item']} | {_money(item['amount'])} | "
                f"{str(item.get('detail') or '-').replace('|', '/')} |"
            )
        lines.append("")

    # 五、综合建议
    lines.append("## 五、综合建议")
    lines.append("")
    lines.append(f"**{recommendation.get('label') or '-'}**")
    lines.append("")
    if recommendation.get("reason"):
        lines.append(f"理由：{recommendation['reason']}")
        lines.append("")
    if recommendation.get("actions"):
        lines.append("行动项：")
        lines.append("")
        for index, action in enumerate(recommendation["actions"], start=1):
            lines.append(f"{index}. {action}")
        lines.append("")

    # 六、数据来源
    lines.append("## 六、数据来源与口径")
    lines.append("")
    if context.get("sources"):
        for key, value in context["sources"].items():
            lines.append(f"- {key}：{value}")
    lines.append(
        f"- 成本费率：加急费率 {cost_model.EXPEDITE_FEE_RATE:.0%}、"
        f"加班 {cost_model.SHIFT_STAGE_DAILY_COST:g} 元/工序·天、"
        f"换线 {cost_model.EQUIPMENT_SETUP_COST:g} 元/台、"
        f"延期 {cost_model.DELAY_PENALTY_PER_DAY + cost_model.DELAY_INDIRECT_COST_PER_DAY:g} 元/天"
        "（v1 经验值，见 modules/cost_model.py）"
    )
    lines.append("")

    return "\n".join(lines)


def write_decision_report(decision, context=None, reports_dir=None):
    """渲染并写入 Markdown 报告，返回文件路径（字符串）。"""
    directory = Path(reports_dir) if reports_dir is not None else DEFAULT_REPORTS_DIR
    directory.mkdir(parents=True, exist_ok=True)

    reference_date = ((context or {}).get("reference_date")) or None
    path = directory / report_file_name(decision, reference_date=reference_date)

    path.write_text(render_decision_report(decision, context), encoding="utf-8")
    return str(path)
