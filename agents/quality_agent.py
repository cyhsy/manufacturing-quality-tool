"""Quality Agent：把已有质量系统包装成 Agent 工具（S2-A-05 / S4-A-01）。

两个能力：

1. ``quality``                 质量总览（S2-A-05，包装原有质量分析）；
2. ``quality_issue_analysis``  质量议题分析（S4-A-01）：按 **产品 / 缺陷 / 时间** 定位问题。

重要：本 Agent **不重写质量系统**，只做包装与编排：

- 取数：``agent_tools.quality_tools`` -> ``tools/quality_tool.query_quality_data()`` -> ``data/quality.csv``
- 统计口径：``modules/quality_analysis.analyze_quality_overview()``
  与 ``modules/defect_analysis`` 中原有函数（缺陷汇总、维度统计）
- 议题趋势：``modules/quality_issue_analysis.py``（本期 vs 上期缺陷率）
- 质量追溯：``tools/traceability_tool.py``（MES 产品 -> 产品映射 -> 质量零件 -> 缺陷 -> 工序 -> 设备）
- 订单影响：``agent_tools.order_tools.get_orders()`` + ``agents.order_agent.evaluate_delivery()``
  （质量异常 -> 设备 -> 影响产品 -> 订单交付风险，S4.1-A-04）
- 改善建议：``knowledge/quality/`` 质量改善知识库（S4-A-03）
- 规则摘要：直接输出原有 ``generate_quality_summary()`` 的句子，不做二次加工
- 根因知识：``modules/root_cause_engine``（原有知识库）

风险判定口径（只做阈值判定，不参与统计计算）：

- 高严重等级缺陷占比 > 30%  -> high（与原页面规则摘要中的阈值一致）
- 主要缺陷占比 >= 50%       -> medium
- 其余                      -> low
"""

import pandas as pd

from agent_tools import order_tools, quality_tools
from agents.order_agent import evaluate_delivery
from modules import quality_issue_analysis


HIGH_SEVERITY_THRESHOLD = 0.3
TOP_DEFECT_RATIO_THRESHOLD = 0.5

# 议题分析：环比缺陷率上升的幅度分级
ISSUE_DECLINE_HIGH_THRESHOLD = 0.2
ISSUE_HIGH_SEVERITY_ALERT = 0.5
ISSUE_IMPROVEMENT_LIMIT = 3

# 订单影响（S4.1-A-04）
ORDER_DETAIL_LIMIT = 10
RISK_RANK = {"high": 0, "medium": 1, "low": 2, "unknown": 3}


def _max_risk(*risks):
    """取最严重的风险等级。"""
    known = [item for item in risks if item in RISK_RANK]
    if not known:
        return "unknown"
    return min(known, key=lambda item: RISK_RANK[item])


# --------------------------------------------------------------------------
# S4.1-A-04 质量异常 -> 生产设备 -> 影响产品 -> 订单风险
# --------------------------------------------------------------------------


def _primary_products(traceability):
    """质量零件经产品映射反向定位到的 MES 产品（有明确映射依据）。"""
    mapped_parts = traceability.get("mapped_quality_parts") or []
    return quality_tools.get_products_for_quality_parts(mapped_parts)


def _equipment_products(traceability):
    """质量异常所涉工序/设备上在产的其它产品（共享设备，潜在影响）。"""
    products = []
    for record in traceability.get("production_records") or []:
        name = str(record.get("产品") or "")
        if name and name not in products:
            products.append(name)
    return products


def assess_affected_orders(traceability, order_limit=ORDER_DETAIL_LIMIT):
    """质量异常 -> 生产设备 -> 影响产品 -> 订单风险（S4.1-A-04）。

    取数走 ``agent_tools.order_tools.get_orders()``（-> ``tools.order_tool.query_orders()``），
    交付风险复用 ``agents.order_agent.evaluate_delivery()`` 的判定口径，
    避免出现第二套订单风险模型。
    """
    if not traceability:
        return {
            "affected_products": [],
            "primary_products": [],
            "equipment_products": [],
            "orders": [],
            "order_count": 0,
            "affected_order_ids": [],
            "delivery_risk": "unknown",
            "risk_source": None,
        }

    primary = _primary_products(traceability)
    equipment_products = _equipment_products(traceability)

    affected_products = list(primary)
    for name in equipment_products:
        if name not in affected_products:
            affected_products.append(name)

    orders_frame = (
        order_tools.get_orders(product=affected_products) if affected_products else None
    )
    if orders_frame is None or orders_frame.empty:
        return {
            "affected_products": affected_products,
            "primary_products": primary,
            "equipment_products": equipment_products,
            "orders": [],
            "order_count": 0,
            "affected_order_ids": [],
            "delivery_risk": "unknown",
            "risk_source": "agent_tools.order_tools.get_orders",
        }

    assessed = []
    for _, row in orders_frame.iterrows():
        product = str(row["product"])
        quantity = int(pd.to_numeric(pd.Series([row["quantity"]]), errors="coerce").fillna(0).iloc[0])
        deadline = pd.to_datetime(row["deadline"], errors="coerce")

        delivery = evaluate_delivery(product=product, quantity=quantity, deadline=deadline)

        assessed.append(
            {
                "order_id": str(row["order_id"]),
                "customer": str(row["customer"]),
                "product": product,
                "quantity": quantity,
                "deadline": None if pd.isna(deadline) else deadline.date().isoformat(),
                "priority": str(row["priority"]),
                "risk": delivery["risk"],
                "reason": delivery["reason"],
                "suggestion": delivery["suggestion"],
                "relation": "直接映射" if product in primary else "共享设备",
            }
        )

    assessed.sort(
        key=lambda item: (
            RISK_RANK.get(item["risk"], 9),
            0 if item["relation"] == "直接映射" else 1,
            item["deadline"] or "",
        )
    )

    delivery_risk = min(
        (item["risk"] for item in assessed),
        key=lambda risk: RISK_RANK.get(risk, 9),
        default="unknown",
    )

    return {
        "affected_products": affected_products,
        "primary_products": primary,
        "equipment_products": equipment_products,
        "orders": assessed[:order_limit],
        "order_count": len(assessed),
        "affected_order_ids": [item["order_id"] for item in assessed],
        "delivery_risk": delivery_risk,
        "risk_source": "agent_tools.order_tools.get_orders + agents.order_agent.evaluate_delivery",
    }


def analyze_quality(process=None, defect_type=None):
    """质量分析：返回结构化的 risk / reason / suggestion 与原有分析结果。"""
    metrics = quality_tools.get_quality_risk_metrics()
    overview = quality_tools.get_quality_overview()

    risk = "low"
    if metrics["high_severity_ratio"] > HIGH_SEVERITY_THRESHOLD:
        risk = "high"
    elif metrics["top_defect_ratio"] >= TOP_DEFECT_RATIO_THRESHOLD:
        risk = "medium"

    reason_parts = [
        f"质量记录 {metrics['record_count']} 条，共 {metrics['total_defects']} 件缺陷，"
        f"涉及 {metrics['defect_type_count']} 类缺陷"
    ]
    if metrics["top_defect_type"]:
        reason_parts.append(
            f"主要缺陷类型为 {metrics['top_defect_type']}"
            f"（占比 {metrics['top_defect_ratio']:.1%}）"
        )
    reason_parts.append(f"高严重等级缺陷占比 {metrics['high_severity_ratio']:.1%}")

    if risk == "high":
        suggestion = "高严重等级缺陷占比偏高，建议立即组织人工复核并追溯责任工序"
    elif risk == "medium":
        suggestion = "主要缺陷类型集中，建议优先复核对应工序与供应商"
    else:
        suggestion = "缺陷分布较分散，保持常规监控并按批次抽检"

    result = {
        "agent": "quality_agent",
        "status": "ok",
        "risk": risk,
        "reason": "；".join(reason_parts),
        "suggestion": suggestion,
        "metrics": metrics,
        "defect_summary": quality_tools.get_defect_summary(limit=10),
        "severity_breakdown": quality_tools.get_severity_breakdown(),
        "summary_lines": overview["summary_lines"],
        "data_source": (
            "data/quality.csv -> tools/quality_tool.query_quality_data() "
            "+ modules/quality_analysis / modules/defect_analysis（原有质量分析逻辑）"
        ),
    }

    if process or defect_type:
        if defect_type:
            result["root_cause_lookup"] = quality_tools.find_root_causes(defect_type, process)
        else:
            result["matched_records"] = len(
                quality_tools.get_quality_records(process=process)
            )

    return result


def _collect_improvements(analysis, limit=ISSUE_IMPROVEMENT_LIMIT):
    """按本期主要缺陷类型检索质量改善知识库。"""
    counts = analysis["recent"].get("defect_type_counts") or {}
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    process = analysis["recent"].get("top_process")

    improvements = []
    for defect_type, quantity in ranked:
        matches = quality_tools.search_improvement_knowledge(
            defect_type=defect_type,
            process=process,
            limit=1,
        )
        if not matches:
            improvements.append(
                {
                    "缺陷类型": defect_type,
                    "缺陷数量": quantity,
                    "案例编号": None,
                    "匹配度": 0.0,
                    "现象": [],
                    "原因": [],
                    "验证方法": [],
                    "改善措施": [],
                    "说明": "知识库暂无对应改善案例，建议补充",
                }
            )
            continue

        case = matches[0]
        improvements.append(
            {
                "缺陷类型": defect_type,
                "缺陷数量": quantity,
                "案例编号": case["案例编号"],
                "标题": case["标题"],
                "类别": case["类别"],
                "匹配度": case["confidence"],
                "命中依据": case["命中依据"],
                "现象": case["现象"],
                "原因": case["原因"],
                "验证方法": case["验证方法"],
                "改善措施": case["改善措施"],
            }
        )

    return improvements


def _issue_verdict(analysis, traceability, affected_orders=None):
    """议题分析结论 -> risk / reason / suggestion。"""
    recent = analysis["recent"]
    verdict = analysis["verdict"]
    worsened = analysis["worsened_dimensions"]

    if verdict == "下降":
        risk = "high" if (analysis["rate_change_ratio"] or 0) > ISSUE_DECLINE_HIGH_THRESHOLD else "medium"
    elif verdict == "改善":
        risk = "low"
    else:
        # 持平 / 无对比数据：看是否存在恶化维度或高严重等级占比偏高
        risk = (
            "medium"
            if worsened or recent["high_severity_ratio"] > ISSUE_HIGH_SEVERITY_ALERT
            else "low"
        )

    reason_parts = [
        (
            f"质量环比{verdict}：本期缺陷 {recent['defect_quantity']} 件 / 批次 "
            f"{recent['batch_quantity']} 件，缺陷率 {recent['defect_rate']:.3%}"
        ),
        f"主要缺陷类型 {recent['top_defect_type']}，主要工序 {recent['top_process']}",
    ]
    if worsened:
        reason_parts.append(
            "环比恶化维度："
            + "、".join(
                f"{item['名称']}（{item['上期缺陷']}→{item['本期缺陷']} 件）"
                for item in worsened[:3]
            )
        )
    if recent["high_severity_ratio"] > ISSUE_HIGH_SEVERITY_ALERT:
        reason_parts.append(f"高严重等级缺陷占比 {recent['high_severity_ratio']:.1%}")

    unmatched = traceability.get("unmatched_processes") or []
    if unmatched:
        reason_parts.append(
            "以下工序在 MES 无对应产线，无法自动关联设备：" + "、".join(unmatched)
        )

    if affected_orders and affected_orders.get("order_count"):
        reason_parts.append(
            f"影响在制订单 {affected_orders['order_count']} 张"
            f"（交付风险 {affected_orders['delivery_risk']}）："
            + "、".join(affected_orders["affected_order_ids"][:5])
        )

    if verdict == "下降" or worsened:
        suggestion = (
            f"优先处置 {recent['top_defect_type']}（{recent['top_process']} 工序）与环比恶化项，"
            "按改善措施执行并跟踪缺陷率变化"
        )
    elif verdict == "改善":
        suggestion = "保持现有改善措施，继续跟踪缺陷率与主要缺陷类型占比"
    else:
        suggestion = "整体持平，建议针对主要缺陷类型开展专项改善并加强过程抽检"

    return risk, "；".join(reason_parts), suggestion


def analyze_quality_issue(
    product=None,
    defect_type=None,
    process=None,
    batch=None,
    days=None,
    start=None,
    end=None,
):
    """质量议题分析（S4-A-01）：按 产品 / 缺陷 / 时间 定位问题并给出改善建议。

    参数：
        product:     产品（匹配质量数据的零件名称或零件编号，包含匹配）。
        defect_type: 缺陷类型（精确匹配）。
        process:     工序（精确匹配）。
        batch:       批次号（包含匹配）。
        days:        本期窗口天数；缺省为可用数据跨度的一半（最少 7 天）。
        start/end:   显式时间范围（优先于 days）。

    返回 dict：
        risk / reason / suggestion（Agent 统一契约）
        scope        查询条件与时间窗
        metrics      本期指标
        trend        环比趋势（含维度恶化/改善清单）
        traceability 追溯结果（工序 -> 设备 -> 生产记录）
        improvements 质量改善知识库建议
        findings     文字结论
    """
    records = quality_tools.get_issue_records(
        product=product,
        batch=batch,
        defect_type=defect_type,
        process=process,
        start=start,
        end=end,
    )

    if records.empty:
        return {
            "agent": "quality_agent",
            "status": "ok",
            "risk": "unknown",
            "reason": "按当前产品 / 缺陷 / 时间条件未找到质量记录",
            "suggestion": "请放宽查询条件（产品名称、缺陷类型或时间范围）后重试",
            "scope": {
                "product": product,
                "defect_type": defect_type,
                "process": process,
                "batch": batch,
                "window": quality_issue_analysis.resolve_window(records, days=days, start=start, end=end),
            },
            "metrics": quality_issue_analysis.summarize_records(records),
            "trend": None,
            "traceability": None,
            "affected_orders": None,
            "improvements": [],
            "findings": ["无匹配记录"],
            "knowledge_base_size": quality_tools.get_quality_knowledge_summary()["case_count"],
        }

    analysis = quality_issue_analysis.analyze_issue(records, days=days, start=start, end=end)
    window = analysis["window"]

    traceability = quality_tools.get_traceability(
        product=product,
        batch=batch,
        defect=defect_type,
        process=process,
        start=window["recent_start"],
        end=window["recent_end"],
    )

    improvements = _collect_improvements(analysis)
    affected_orders = assess_affected_orders(traceability)
    risk, reason, suggestion = _issue_verdict(analysis, traceability, affected_orders)

    findings = list(analysis["findings"])
    combined_risk = _max_risk(risk, affected_orders.get("delivery_risk"))

    if affected_orders["order_count"]:
        findings.append(
            f"影响订单：{'、'.join(affected_orders['affected_order_ids'][:5])}"
            f"（共 {affected_orders['order_count']} 张，交付风险 {affected_orders['delivery_risk']}，"
            f"综合风险 {combined_risk}）"
        )
    else:
        findings.append("未关联到受影响订单")

    return {
        "agent": "quality_agent",
        "status": "ok",
        "risk": risk,
        "reason": reason,
        "suggestion": suggestion,
        "combined_risk": combined_risk,
        "scope": {
            "product": product,
            "defect_type": defect_type,
            "process": process,
            "batch": batch,
            "window": window,
        },
        "metrics": analysis["recent"],
        "trend": {
            "verdict": analysis["verdict"],
            "rate_change": analysis["rate_change"],
            "rate_change_ratio": analysis["rate_change_ratio"],
            "recent": analysis["recent"],
            "previous": analysis["previous"],
            "dimension_trends": analysis["dimension_trends"],
            "worsened_dimensions": analysis["worsened_dimensions"],
            "improved_dimensions": analysis["improved_dimensions"],
        },
        "traceability": traceability,
        "affected_orders": affected_orders,
        "improvements": improvements,
        "findings": findings,
        "knowledge_base_size": quality_tools.get_quality_knowledge_summary()["case_count"],
    }


def run(capabilities=None, arguments=None):
    """Agent 统一入口。

    capabilities：
        quality                 质量总览（S2-A-05）；
        quality_issue_analysis  质量议题分析（S4-A-01）。
    """
    capabilities = list(capabilities or ["quality"])
    arguments = dict(arguments or {})

    if "quality_issue_analysis" in capabilities:
        result = analyze_quality_issue(
            product=arguments.get("part_name") or arguments.get("product"),
            defect_type=arguments.get("defect_type"),
            process=arguments.get("process"),
            batch=arguments.get("batch"),
            days=arguments.get("days"),
            start=arguments.get("start"),
            end=arguments.get("end"),
        )
        result["capabilities"] = capabilities
        return result

    result = analyze_quality(
        process=arguments.get("process"),
        defect_type=arguments.get("defect_type"),
    )
    result["capabilities"] = capabilities
    return result


def main():
    """命令行入口。

    示例：
        python -m agents.quality_agent                     # 质量总览
        python -m agents.quality_agent --issue             # 质量议题分析（最近趋势）
        python -m agents.quality_agent --issue --defect 尺寸偏大
        python -m agents.quality_agent --issue --product 支架 --process 铣削
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Quality Agent 质量分析与议题分析")
    parser.add_argument("--issue", action="store_true", help="执行质量议题分析（S4-A-01）")
    parser.add_argument("--product", help="产品 / 零件名称，如 支架")
    parser.add_argument("--defect", help="缺陷类型，如 尺寸偏大")
    parser.add_argument("--process", help="工序，如 铣削")
    parser.add_argument("--batch", help="批次号，如 LOT-202605")
    parser.add_argument("--days", type=int, help="本期窗口天数")
    parser.add_argument("--start", help="起始日期，如 2026-04-30")
    parser.add_argument("--end", help="结束日期，如 2026-05-14")
    args = parser.parse_args()

    if args.issue:
        payload = analyze_quality_issue(
            product=args.product,
            defect_type=args.defect,
            process=args.process,
            batch=args.batch,
            days=args.days,
            start=args.start,
            end=args.end,
        )
    else:
        payload = analyze_quality(process=args.process, defect_type=args.defect)

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
