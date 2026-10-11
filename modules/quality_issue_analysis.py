"""质量议题分析（S4-A-01 的分析口径）。

输入：已按 产品 / 缺陷 / 工序 / 批次 过滤的质量记录（DataFrame）；
输出：时间窗对比、缺陷率变化、维度恶化/改善清单与文字结论。

时间窗口径：

- 以数据中**最新日期**为基准（不用系统当天，避免数据滞后导致窗口为空）；
- 默认窗口长度 = 可用数据跨度的一半（最少 7 天）；
- 对比窗口 = 紧邻本期的等长上期（环比）；
- 也可显式给出 ``start`` / ``end``。

指标口径：

- **缺陷率** = 缺陷数量合计 / 批次数量合计（与数据字段一致，避免只看绝对数量被产量干扰）；
- 结论：环比缺陷率上升 > 5% 记为「下降」，下降 > 5% 记为「改善」，否则「持平」；
- 维度趋势按缺陷数量变化绝对值排序，单期数量低于 ``min_defects`` 的维度不参与，
  避免小样本噪声。
"""

import math

import pandas as pd


DATE_COLUMN = "日期"
DEFECT_COUNT_COLUMN = "缺陷数量"
BATCH_QUANTITY_COLUMN = "批次数量"
DEFECT_TYPE_COLUMN = "缺陷类型"
PROCESS_COLUMN = "工序"
PART_NAME_COLUMN = "零件名称"
SUPPLIER_COLUMN = "供应商"
SEVERITY_COLUMN = "严重等级"

HIGH_SEVERITY_VALUE = "高"

MIN_WINDOW_DAYS = 7
DECLINE_THRESHOLD = 0.05
DEFAULT_MIN_DEFECTS = 5
MIN_RECORDS_FOR_TREND = 5


def _to_number(value):
    return pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0).iloc[0]


def _blank_window():
    return {
        "days": None,
        "reference": None,
        "recent_start": None,
        "recent_end": None,
        "previous_start": None,
        "previous_end": None,
    }


def _as_iso(value):
    return None if value is None else pd.Timestamp(value).date().isoformat()


def resolve_window(records, days=None, start=None, end=None):
    """解析时间窗口：返回本期与上期（环比）的起止日期。"""
    if records is None or records.empty:
        return _blank_window()

    dates = pd.to_datetime(records[DATE_COLUMN], errors="coerce").dropna()
    if dates.empty:
        return _blank_window()

    data_min, data_max = dates.min(), dates.max()

    if start is not None or end is not None:
        recent_start = pd.Timestamp(start) if start is not None else data_min
        recent_end = pd.Timestamp(end) if end is not None else data_max
        span = max(1, int((recent_end - recent_start).days) + 1)
        previous_end = recent_start - pd.Timedelta(days=1)
        previous_start = previous_end - pd.Timedelta(days=span - 1)
        return {
            "days": span,
            "reference": _as_iso(recent_end),
            "recent_start": _as_iso(recent_start),
            "recent_end": _as_iso(recent_end),
            "previous_start": _as_iso(previous_start),
            "previous_end": _as_iso(previous_end),
        }

    total_span = max(1, int((data_max - data_min).days) + 1)
    span = int(days) if days else max(MIN_WINDOW_DAYS, math.ceil(total_span / 2))

    recent_end = data_max
    recent_start = recent_end - pd.Timedelta(days=span - 1)
    previous_end = recent_start - pd.Timedelta(days=1)
    previous_start = previous_end - pd.Timedelta(days=span - 1)

    return {
        "days": span,
        "reference": _as_iso(data_max),
        "recent_start": _as_iso(recent_start),
        "recent_end": _as_iso(recent_end),
        "previous_start": _as_iso(previous_start),
        "previous_end": _as_iso(previous_end),
    }


def records_between(records, start, end):
    """按日期区间（含端点）截取记录；区间为空时返回空表。"""
    if records is None or records.empty or start is None or end is None:
        return records.iloc[0:0].copy() if records is not None else pd.DataFrame()

    dates = pd.to_datetime(records[DATE_COLUMN], errors="coerce")
    mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    return records.loc[mask]


def summarize_records(records):
    """汇总一段记录的核心质量指标。"""
    if records is None or records.empty:
        return {
            "record_count": 0,
            "defect_quantity": 0,
            "batch_quantity": 0,
            "defect_rate": 0.0,
            "defect_type_count": 0,
            "high_severity_ratio": 0.0,
            "top_defect_type": None,
            "top_process": None,
            "top_part": None,
            "top_supplier": None,
            "defect_type_counts": {},
        }

    defect_quantity = int(pd.to_numeric(records[DEFECT_COUNT_COLUMN], errors="coerce").fillna(0).sum())
    batch_quantity = int(pd.to_numeric(records[BATCH_QUANTITY_COLUMN], errors="coerce").fillna(0).sum())

    def _grouped(column):
        if column not in records.columns or records.empty:
            return {}
        grouped = records.groupby(column)[DEFECT_COUNT_COLUMN].sum()
        return {str(key): int(value) for key, value in grouped.items()}

    defect_counts = _grouped(DEFECT_TYPE_COLUMN)
    process_counts = _grouped(PROCESS_COLUMN)
    part_counts = _grouped(PART_NAME_COLUMN)
    supplier_counts = _grouped(SUPPLIER_COLUMN)

    high_severity_quantity = 0
    if SEVERITY_COLUMN in records.columns:
        high_rows = records.loc[records[SEVERITY_COLUMN].astype(str) == HIGH_SEVERITY_VALUE]
        high_severity_quantity = int(
            pd.to_numeric(high_rows[DEFECT_COUNT_COLUMN], errors="coerce").fillna(0).sum()
        )

    def _top(counts):
        if not counts:
            return None
        return max(counts.items(), key=lambda item: item[1])[0]

    return {
        "record_count": int(len(records)),
        "defect_quantity": defect_quantity,
        "batch_quantity": batch_quantity,
        "defect_rate": (defect_quantity / batch_quantity) if batch_quantity else 0.0,
        "defect_type_count": len(defect_counts),
        "high_severity_ratio": (high_severity_quantity / defect_quantity) if defect_quantity else 0.0,
        "top_defect_type": _top(defect_counts),
        "top_process": _top(process_counts),
        "top_part": _top(part_counts),
        "top_supplier": _top(supplier_counts),
        "defect_type_counts": defect_counts,
    }


def dimension_trends(recent, previous, dimension, min_defects=DEFAULT_MIN_DEFECTS, limit=5):
    """按维度（缺陷类型 / 工序 / 零件…）对比本期与上期缺陷数量。"""
    if dimension not in getattr(recent, "columns", []) and dimension not in getattr(previous, "columns", []):
        return []

    def _counts(records):
        if records is None or records.empty or dimension not in records.columns:
            return {}
        grouped = records.groupby(dimension)[DEFECT_COUNT_COLUMN].sum()
        return {str(key): int(value) for key, value in grouped.items()}

    recent_counts = _counts(recent)
    previous_counts = _counts(previous)

    trends = []
    for name in set(recent_counts) | set(previous_counts):
        current = recent_counts.get(name, 0)
        baseline = previous_counts.get(name, 0)
        if max(current, baseline) < min_defects:
            continue

        delta = current - baseline
        change_ratio = (delta / baseline) if baseline else None
        trends.append(
            {
                "维度": dimension,
                "名称": name,
                "本期缺陷": current,
                "上期缺陷": baseline,
                "变化": delta,
                "变化率": change_ratio,
                "方向": "恶化" if delta > 0 else ("改善" if delta < 0 else "持平"),
            }
        )

    trends.sort(key=lambda item: (-abs(item["变化"]), item["名称"]))
    return trends[:limit] if limit else trends


def analyze_issue(records, days=None, start=None, end=None, min_defects=DEFAULT_MIN_DEFECTS):
    """质量议题分析主入口。

    返回 dict：window / recent / previous / rate_change / rate_change_ratio /
    verdict / dimension_trends / worsened_dimensions / improved_dimensions / findings。
    """
    window = resolve_window(records, days=days, start=start, end=end)
    recent = records_between(records, window["recent_start"], window["recent_end"])
    previous = records_between(records, window["previous_start"], window["previous_end"])

    recent_summary = summarize_records(recent)
    previous_summary = summarize_records(previous)

    rate_change = recent_summary["defect_rate"] - previous_summary["defect_rate"]
    if previous_summary["defect_rate"]:
        rate_change_ratio = rate_change / previous_summary["defect_rate"]
    else:
        rate_change_ratio = None

    if previous_summary["record_count"] == 0:
        verdict = "无对比数据"
    elif rate_change_ratio is not None and rate_change_ratio > DECLINE_THRESHOLD:
        verdict = "下降"
    elif rate_change_ratio is not None and rate_change_ratio < -DECLINE_THRESHOLD:
        verdict = "改善"
    else:
        verdict = "持平"

    trends = dimension_trends(recent, previous, DEFECT_TYPE_COLUMN, min_defects=min_defects, limit=5)
    trends += dimension_trends(recent, previous, PROCESS_COLUMN, min_defects=min_defects, limit=5)

    worsened = [item for item in trends if item["方向"] == "恶化"]
    improved = [item for item in trends if item["方向"] == "改善"]

    findings = _build_findings(window, recent_summary, previous_summary, verdict, rate_change_ratio, worsened)

    return {
        "window": window,
        "recent": recent_summary,
        "previous": previous_summary,
        "rate_change": rate_change,
        "rate_change_ratio": rate_change_ratio,
        "verdict": verdict,
        "dimension_trends": trends,
        "worsened_dimensions": worsened,
        "improved_dimensions": improved,
        "findings": findings,
    }


def _format_ratio(value):
    return "无上期数据" if value is None else f"{value:+.1%}"


def _build_findings(window, recent, previous, verdict, rate_change_ratio, worsened):
    """生成文字结论。"""
    findings = [
        (
            f"对比窗口：{window['recent_start']} ~ {window['recent_end']}（{window['days']} 天）"
            f"环比 {window['previous_start']} ~ {window['previous_end']}"
        ),
        (
            f"本期缺陷 {recent['defect_quantity']} 件 / 批次 {recent['batch_quantity']} 件，"
            f"缺陷率 {recent['defect_rate']:.3%}；"
            f"上期缺陷 {previous['defect_quantity']} 件，缺陷率 {previous['defect_rate']:.3%}"
        ),
        f"环比趋势：质量{verdict}（缺陷率变化 {_format_ratio(rate_change_ratio)}）",
    ]

    if recent["top_defect_type"]:
        count = recent["defect_type_counts"].get(recent["top_defect_type"], 0)
        findings.append(f"本期主要缺陷类型：{recent['top_defect_type']}（{count} 件）")
    if recent["top_process"]:
        findings.append(f"本期主要工序：{recent['top_process']}")
    if recent["top_part"]:
        findings.append(f"本期主要零件：{recent['top_part']}")
    if recent["top_supplier"]:
        findings.append(f"本期主要供应商：{recent['top_supplier']}")
    if recent["high_severity_ratio"]:
        findings.append(f"高严重等级缺陷占比：{recent['high_severity_ratio']:.1%}")

    if worsened:
        detail = "、".join(
            f"{item['名称']}（{item['上期缺陷']}→{item['本期缺陷']} 件）" for item in worsened[:3]
        )
        findings.append(f"环比恶化维度：{detail}")
    else:
        findings.append("未发现明显环比恶化的缺陷类型或工序")

    if recent["record_count"] < MIN_RECORDS_FOR_TREND:
        findings.append(
            f"注意：本期仅 {recent['record_count']} 条记录，样本量较小，趋势结论仅供参考"
        )

    return findings
