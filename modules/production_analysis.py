"""生产分析（MES 生产数据 data/production.csv）。

分析口径：
- yield_rate 支持 "96%" 与 0.96 两种写法，统一解析为 0~1 小数。
- 良率均值为百分比口径；对外同时给出「在产产线平均良率」与「全部产线平均良率」，
  避免把停机产线的 0% 混入在产良率造成误判。
- 产能对比使用在产（running）产线的日产能；若没有在产产线则回退到全部产线产能。
"""

import math

import pandas as pd

from modules.order_analysis import load_orders
from tools.production_tool import STATUS_LABELS, query_production_capacity


PRODUCTION_DISPLAY_COLUMNS = {
    "product": "产品",
    "process": "工序",
    "equipment": "设备编号",
    "daily_capacity": "日产能",
    "yield_rate": "良率",
    "status": "产线状态",
}

STATUS_ORDER = ["running", "idle", "maintenance", "stopped"]
YIELD_RATE_VALUE_COLUMN = "yield_rate_value"


def parse_yield_rate(values):
    """把 "96%" / 96 / 0.96 / "0.96" 统一解析为 0~1 的小数。"""
    text = pd.Series(values).astype(str).str.strip().str.replace("%", "", regex=False)
    numbers = pd.to_numeric(text, errors="coerce")

    # 大于 1 视为百分比数值（如 96），否则视为已是小数（如 0.96）
    ratios = numbers.where(numbers <= 1, numbers / 100)
    return ratios.fillna(0.0).clip(lower=0.0, upper=1.0)


def load_production(**query_kwargs):
    """读取 MES 生产数据，并补充数值化的良率列 yield_rate_value。"""
    df = query_production_capacity(**query_kwargs).copy()
    if df.empty:
        return df

    df["daily_capacity"] = pd.to_numeric(df["daily_capacity"], errors="coerce").fillna(0).astype("int64")
    df[YIELD_RATE_VALUE_COLUMN] = parse_yield_rate(df["yield_rate"])
    return df


def to_display_frame(df):
    """转换为中文表头的展示用表（仅保留生产标准字段，隐藏辅助列）。"""
    keep_columns = [column for column in PRODUCTION_DISPLAY_COLUMNS if column in df.columns]
    display = df[keep_columns].rename(columns=PRODUCTION_DISPLAY_COLUMNS).copy()

    if "产线状态" in display.columns:
        display["产线状态"] = display["产线状态"].map(
            lambda value: STATUS_LABELS.get(str(value).lower(), value)
        )

    return display.reset_index(drop=True)


def _empty_summary():
    return {
        "product_count": 0,
        "process_count": 0,
        "equipment_count": 0,
        "line_count": 0,
        "total_daily_capacity": 0,
        "running_daily_capacity": 0,
        "running_line_count": 0,
        "average_yield_rate": 0.0,
        "overall_average_yield_rate": 0.0,
    }


def summarize_production(df=None):
    """生产总览指标（产品/工序/设备数、日产能、在产产能、平均良率）。"""
    production = load_production() if df is None else df
    if production.empty:
        return _empty_summary()

    status = production["status"].astype(str).str.lower()
    capacity = pd.to_numeric(production["daily_capacity"], errors="coerce").fillna(0)
    yield_values = production.get(YIELD_RATE_VALUE_COLUMN)
    if yield_values is None:
        yield_values = parse_yield_rate(production["yield_rate"])

    running_mask = status == "running"
    running_yield = yield_values[running_mask]

    return {
        "product_count": int(production["product"].nunique()),
        "process_count": int(production["process"].nunique()),
        "equipment_count": int(production["equipment"].nunique()),
        "line_count": int(len(production)),
        "total_daily_capacity": int(capacity.sum()),
        "running_daily_capacity": int(capacity[running_mask].sum()),
        "running_line_count": int(running_mask.sum()),
        "average_yield_rate": float(running_yield.mean()) if len(running_yield) else 0.0,
        "overall_average_yield_rate": float(yield_values.mean()) if len(yield_values) else 0.0,
    }


def get_status_breakdown(df=None):
    """按产线状态汇总产线数量、日产能与占比。"""
    columns = ["产线状态", "产线数量", "日产能合计", "占比"]
    production = load_production() if df is None else df
    if production.empty:
        return pd.DataFrame(columns=columns)

    data = production.copy()
    data["产线状态"] = data["status"].astype(str).str.lower().map(
        lambda value: STATUS_LABELS.get(value, value)
    )
    data["日产能合计"] = pd.to_numeric(data["daily_capacity"], errors="coerce").fillna(0)

    summary = data.groupby("产线状态", as_index=False).agg(
        产线数量=("product", "size"),
        日产能合计=("日产能合计", "sum"),
    )

    label_order = [STATUS_LABELS[value] for value in STATUS_ORDER]
    summary["_排序"] = summary["产线状态"].map(
        lambda value: label_order.index(value) if value in label_order else len(label_order)
    )
    summary = (
        summary.sort_values(["_排序", "产线状态"])
        .drop(columns="_排序")
        .reset_index(drop=True)
    )

    total_lines = summary["产线数量"].sum()
    summary["占比"] = summary["产线数量"] / total_lines if total_lines else 0
    return summary[columns]


def get_process_breakdown(df=None):
    """按工序汇总日产能与平均良率（按日产能降序）。"""
    columns = ["工序", "产线数量", "日产能合计", "平均良率"]
    production = load_production() if df is None else df
    if production.empty:
        return pd.DataFrame(columns=columns)

    data = production.copy()
    data["日产能合计"] = pd.to_numeric(data["daily_capacity"], errors="coerce").fillna(0)
    yield_values = data.get(YIELD_RATE_VALUE_COLUMN)
    data["良率数值"] = (
        yield_values if yield_values is not None else parse_yield_rate(data["yield_rate"])
    )

    summary = data.groupby("process", as_index=False).agg(
        产线数量=("equipment", "size"),
        日产能合计=("日产能合计", "sum"),
        平均良率=("良率数值", "mean"),
    )
    summary = summary.rename(columns={"process": "工序"})

    return (
        summary.sort_values("日产能合计", ascending=False)
        .reset_index(drop=True)[columns]
    )


def calculate_capacity_vs_demand(orders_df=None, production_df=None, today=None):
    """对比在手订单需求与在产产能，判断是否存在产能风险。

    返回 dict：
        total_demand     在手订单总数量
        daily_capacity   用于测算的日产能（在产产线优先）
        required_days    按日产能完成全部订单所需天数（向上取整）
        earliest_deadline 最早交付日期
        available_days   今天距最早交付日期的天数
        capacity_risk    True 表示所需天数已超过最早交期可用天数
    """
    orders = load_orders() if orders_df is None else orders_df
    production = load_production() if production_df is None else production_df

    total_demand = 0
    if not orders.empty:
        total_demand = int(pd.to_numeric(orders["quantity"], errors="coerce").fillna(0).sum())

    summary = summarize_production(production)
    daily_capacity = summary["running_daily_capacity"] or summary["total_daily_capacity"]

    required_days = math.ceil(total_demand / daily_capacity) if daily_capacity > 0 else None

    earliest_deadline = None
    if not orders.empty:
        deadline = pd.to_datetime(orders["deadline"], errors="coerce").dropna()
        if not deadline.empty:
            earliest_deadline = deadline.min().date()

    reference = (
        pd.Timestamp(today).normalize()
        if today is not None
        else pd.Timestamp.today().normalize()
    )
    available_days = (
        None
        if earliest_deadline is None
        else int((pd.Timestamp(earliest_deadline) - reference).days)
    )

    return {
        "total_demand": total_demand,
        "daily_capacity": int(daily_capacity),
        "required_days": required_days,
        "earliest_deadline": earliest_deadline,
        "available_days": available_days,
        "capacity_risk": bool(
            required_days is not None
            and available_days is not None
            and required_days > available_days
        ),
    }


def production_insights(orders_df=None, production_df=None, today=None):
    """生成驾驶舱「生产能力」相关文字结论。"""
    summary = summarize_production(production_df)
    if summary["line_count"] == 0:
        return ["当前没有生产数据。"]

    lines = [
        (
            f"MES 覆盖 {summary['product_count']} 种产品、{summary['process_count']} 道工序、"
            f"{summary['equipment_count']} 台设备，共 {summary['line_count']} 条产线。"
        ),
        (
            f"总日产能 {summary['total_daily_capacity']} 件，其中在产产线 "
            f"{summary['running_line_count']} 条、日产能 {summary['running_daily_capacity']} 件；"
            f"在产平均良率 {summary['average_yield_rate']:.1%}。"
        ),
    ]

    comparison = calculate_capacity_vs_demand(orders_df=orders_df, production_df=production_df, today=today)
    if comparison["required_days"] is not None:
        lines.append(
            f"按当前在产日产能完成在手订单约需 {comparison['required_days']} 天，"
            f"最早交付日期 {comparison['earliest_deadline']}"
            f"（距今 {comparison['available_days']} 天）。"
        )
    if comparison["capacity_risk"]:
        lines.append("产能提示：所需生产天数已超过最早交期可用天数，存在交付风险。")

    return lines
