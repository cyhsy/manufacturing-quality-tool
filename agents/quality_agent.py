"""Quality Agent：把已有质量系统包装成 Agent 工具（S2-A-05）。

重要：本 Agent **不重写质量系统**，只做包装：

- 取数：``agent_tools.quality_tools`` -> ``tools/quality_tool.query_quality_data()`` -> ``data/quality.csv``
- 统计口径：``modules/quality_analysis.analyze_quality_overview()``
  与 ``modules/defect_analysis`` 中原有函数（缺陷汇总、维度统计）
- 规则摘要：直接输出原有 ``generate_quality_summary()`` 的句子，不做二次加工
- 根因知识：``modules/root_cause_engine``（原有知识库）

风险判定口径（只做阈值判定，不参与统计计算）：

- 高严重等级缺陷占比 > 30%  -> high（与原页面规则摘要中的阈值一致）
- 主要缺陷占比 >= 50%       -> medium
- 其余                      -> low
"""

from agent_tools import quality_tools


HIGH_SEVERITY_THRESHOLD = 0.3
TOP_DEFECT_RATIO_THRESHOLD = 0.5


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


def run(capabilities=None, arguments=None):
    """Agent 统一入口（quality_agent 只提供质量能力）。"""
    capabilities = list(capabilities or ["quality"])
    arguments = dict(arguments or {})

    result = analyze_quality(
        process=arguments.get("process"),
        defect_type=arguments.get("defect_type"),
    )
    result["capabilities"] = capabilities
    return result


def main():
    """命令行入口：``python -m agents.quality_agent``。"""
    import json

    print(json.dumps(run(capabilities=["quality"]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
