"""订单分析（ERP 模拟订单数据 data/orders.csv）。

分析口径：
- quantity 统一按数值处理，缺失按 0 计。
- deadline 为 ISO 日期，统一解析为 datetime 后用于交期判断。
- priority 固定为 high / normal / low 三档，展示时映射为 高 / 普通 / 低。
"""

import pandas as pd

from tools.order_tool import PRIORITY_LABELS, query_orders


ORDER_DISPLAY_COLUMNS = {
    "order_id": "订单编号",
    "customer": "客户",
    "product": "产品",
    "quantity": "数量",
    "deadline": "交付日期",
    "priority": "优先级",
}

PRIORITY_ORDER = ["high", "normal", "low"]
DEFAULT_URGENT_DAYS = 14


def load_orders(**query_kwargs):
    """读取订单数据，并把 quantity 与 deadline 转为分析所需类型。"""
    df = query_orders(**query_kwargs).copy()
    if df.empty:
        return df

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype("int64")
    df["deadline"] = pd.to_datetime(df["deadline"], errors="coerce")
    return df


def to_display_frame(df):
    """转换为中文表头的展示用表（仅保留订单标准字段）。"""
    keep_columns = [column for column in ORDER_DISPLAY_COLUMNS if column in df.columns]
    display = df[keep_columns].rename(columns=ORDER_DISPLAY_COLUMNS).copy()

    if "优先级" in display.columns:
        display["优先级"] = display["优先级"].map(
            lambda value: PRIORITY_LABELS.get(str(value).lower(), value)
        )
    if "交付日期" in display.columns:
        display["交付日期"] = pd.to_datetime(display["交付日期"], errors="coerce").dt.date

    return display.reset_index(drop=True)


def summarize_orders(df=None):
    """订单总览指标（订单数、数量、客户数、高优先级数、交期范围）。"""
    orders = load_orders() if df is None else df
    if orders.empty:
        return {
            "order_count": 0,
            "total_quantity": 0,
            "customer_count": 0,
            "product_count": 0,
            "high_priority_count": 0,
            "earliest_deadline": None,
            "latest_deadline": None,
        }

    quantity = pd.to_numeric(orders["quantity"], errors="coerce").fillna(0)
    deadline = pd.to_datetime(orders["deadline"], errors="coerce").dropna()
    priority = orders["priority"].astype(str).str.lower()

    return {
        "order_count": int(len(orders)),
        "total_quantity": int(quantity.sum()),
        "customer_count": int(orders["customer"].nunique()),
        "product_count": int(orders["product"].nunique()),
        "high_priority_count": int((priority == "high").sum()),
        "earliest_deadline": None if deadline.empty else deadline.min().date(),
        "latest_deadline": None if deadline.empty else deadline.max().date(),
    }


def get_priority_breakdown(df=None):
    """按优先级汇总订单数、数量与占比（中文表头，固定 高→普通→低 顺序）。"""
    columns = ["优先级", "订单数", "总数量", "占比"]
    orders = load_orders() if df is None else df
    if orders.empty:
        return pd.DataFrame(columns=columns)

    data = orders.copy()
    data["优先级"] = data["priority"].astype(str).str.lower().map(
        lambda value: PRIORITY_LABELS.get(value, value)
    )
    data["总数量"] = pd.to_numeric(data["quantity"], errors="coerce").fillna(0)

    summary = data.groupby("优先级", as_index=False).agg(
        订单数=("order_id", "size"),
        总数量=("总数量", "sum"),
    )

    label_order = [PRIORITY_LABELS[value] for value in PRIORITY_ORDER]
    summary["_排序"] = summary["优先级"].map(
        lambda value: label_order.index(value) if value in label_order else len(label_order)
    )
    summary = (
        summary.sort_values(["_排序", "优先级"])
        .drop(columns="_排序")
        .reset_index(drop=True)
    )

    total_orders = summary["订单数"].sum()
    summary["占比"] = summary["订单数"] / total_orders if total_orders else 0
    return summary[columns]


def get_urgent_orders(df=None, limit=5):
    """按交付日期升序返回最紧急的订单（保留订单原始字段）。"""
    orders = load_orders() if df is None else df
    if orders.empty or limit is None or limit <= 0:
        return orders

    return (
        orders.sort_values("deadline", ascending=True)
        .head(limit)
        .reset_index(drop=True)
    )


def order_insights(df=None, today=None, urgent_days=DEFAULT_URGENT_DAYS):
    """生成驾驶舱「订单」模块的文字结论。"""
    orders = load_orders() if df is None else df
    if orders.empty:
        return ["当前没有订单数据。"]

    summary = summarize_orders(orders)
    lines = [
        (
            f"在手订单 {summary['order_count']} 单，合计 {summary['total_quantity']} 件，"
            f"覆盖 {summary['customer_count']} 家客户、{summary['product_count']} 种产品。"
        ),
        (
            f"高优先级订单 {summary['high_priority_count']} 单；"
            f"交付窗口 {summary['earliest_deadline']} ~ {summary['latest_deadline']}。"
        ),
    ]

    reference = (
        pd.Timestamp(today).normalize()
        if today is not None
        else pd.Timestamp.today().normalize()
    )
    deadline = pd.to_datetime(orders["deadline"], errors="coerce")
    horizon = reference + pd.Timedelta(days=urgent_days)

    due_soon_count = int(((deadline >= reference) & (deadline <= horizon)).sum())
    if due_soon_count:
        lines.append(f"{urgent_days} 天内需交付 {due_soon_count} 单，建议优先排产。")

    overdue_count = int((deadline < reference).sum())
    if overdue_count:
        lines.append(f"已有 {overdue_count} 单超过交付日期，需立即处理。")

    return lines
