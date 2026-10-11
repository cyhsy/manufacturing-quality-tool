"""设备分析（设备台账模拟数据 data/equipment.csv）。

分析口径：
- 设备状态分三档：normal 正常 / warning 预警 / fault 故障；非 normal 统一计为异常。
- capacity 为日产能，异常设备产能同样统计，便于评估产能损失。
- 默认维保周期 60 天，超过该天数未保养的设备计入「维保超期」。
"""

import pandas as pd

from tools.equipment_tool import STATUS_LABELS, query_equipment_status


EQUIPMENT_DISPLAY_COLUMNS = {
    "equipment_id": "设备编号",
    "equipment_type": "设备类型",
    "status": "状态",
    "capacity": "日产能",
    "last_maintenance": "上次保养",
}

STATUS_ORDER = ["normal", "warning", "fault"]
ABNORMAL_STATUSES = ("warning", "fault")
DEFAULT_MAINTENANCE_INTERVAL_DAYS = 60


def load_equipment(**query_kwargs):
    """读取设备台账，并把 capacity 转为数值、last_maintenance 转为日期。"""
    df = query_equipment_status(**query_kwargs).copy()
    if df.empty:
        return df

    df["capacity"] = pd.to_numeric(df["capacity"], errors="coerce").fillna(0).astype("int64")
    df["last_maintenance"] = pd.to_datetime(df["last_maintenance"], errors="coerce")
    return df


def to_display_frame(df):
    """转换为中文表头的展示用表（仅保留设备标准字段）。"""
    keep_columns = [column for column in EQUIPMENT_DISPLAY_COLUMNS if column in df.columns]
    display = df[keep_columns].rename(columns=EQUIPMENT_DISPLAY_COLUMNS).copy()

    if "状态" in display.columns:
        display["状态"] = display["状态"].map(
            lambda value: STATUS_LABELS.get(str(value).lower(), value)
        )
    if "上次保养" in display.columns:
        display["上次保养"] = pd.to_datetime(display["上次保养"], errors="coerce").dt.date

    return display.reset_index(drop=True)


def summarize_equipment(df=None, today=None):
    """设备总览指标（总数、正常/预警/故障数量、正常率、产能、维保超期数）。"""
    equipment = load_equipment() if df is None else df
    if equipment.empty:
        return {
            "total_equipment": 0,
            "normal_count": 0,
            "warning_count": 0,
            "fault_count": 0,
            "abnormal_count": 0,
            "normal_ratio": 0.0,
            "total_capacity": 0,
            "abnormal_capacity": 0,
            "maintenance_due_count": 0,
        }

    status = equipment["status"].astype(str).str.lower()
    capacity = pd.to_numeric(equipment["capacity"], errors="coerce").fillna(0)
    normal_mask = status == "normal"

    return {
        "total_equipment": int(len(equipment)),
        "normal_count": int(normal_mask.sum()),
        "warning_count": int((status == "warning").sum()),
        "fault_count": int((status == "fault").sum()),
        "abnormal_count": int((~normal_mask).sum()),
        "normal_ratio": float(normal_mask.sum() / len(equipment)),
        "total_capacity": int(capacity.sum()),
        "abnormal_capacity": int(capacity.loc[~normal_mask].sum()),
        "maintenance_due_count": int(len(get_maintenance_due(equipment, today=today))),
    }


def get_status_breakdown(df=None):
    """按设备状态汇总设备数量、日产能与占比（固定 正常→预警→故障 顺序）。"""
    columns = ["设备状态", "设备数量", "日产能合计", "占比"]
    equipment = load_equipment() if df is None else df
    if equipment.empty:
        return pd.DataFrame(columns=columns)

    data = equipment.copy()
    data["设备状态"] = data["status"].astype(str).str.lower().map(
        lambda value: STATUS_LABELS.get(value, value)
    )
    data["日产能合计"] = pd.to_numeric(data["capacity"], errors="coerce").fillna(0)

    summary = data.groupby("设备状态", as_index=False).agg(
        设备数量=("equipment_id", "size"),
        日产能合计=("日产能合计", "sum"),
    )

    label_order = [STATUS_LABELS[value] for value in STATUS_ORDER]
    summary["_排序"] = summary["设备状态"].map(
        lambda value: label_order.index(value) if value in label_order else len(label_order)
    )
    summary = (
        summary.sort_values(["_排序", "设备状态"])
        .drop(columns="_排序")
        .reset_index(drop=True)
    )

    total_equipment = summary["设备数量"].sum()
    summary["占比"] = summary["设备数量"] / total_equipment if total_equipment else 0
    return summary[columns]


def get_abnormal_equipment(df=None):
    """返回预警与故障设备，故障优先排序。"""
    equipment = load_equipment() if df is None else df
    if equipment.empty:
        return equipment

    status = equipment["status"].astype(str).str.lower()
    abnormal = equipment.loc[status.isin(ABNORMAL_STATUSES)].copy()
    if abnormal.empty:
        return abnormal.reset_index(drop=True)

    severity = {"fault": 0, "warning": 1}
    abnormal["_排序"] = abnormal["status"].astype(str).str.lower().map(
        lambda value: severity.get(value, 99)
    )
    return (
        abnormal.sort_values(["_排序", "equipment_id"])
        .drop(columns="_排序")
        .reset_index(drop=True)
    )


def get_maintenance_due(
    df=None,
    days=DEFAULT_MAINTENANCE_INTERVAL_DAYS,
    today=None,
):
    """返回超过 days 天未保养的设备（按未保养天数降序）。"""
    columns = [
        "equipment_id",
        "equipment_type",
        "status",
        "capacity",
        "last_maintenance",
        "未保养天数",
    ]
    equipment = load_equipment() if df is None else df
    if equipment.empty:
        return pd.DataFrame(columns=columns)

    reference = (
        pd.Timestamp(today).normalize()
        if today is not None
        else pd.Timestamp.today().normalize()
    )
    last_maintenance = pd.to_datetime(equipment["last_maintenance"], errors="coerce")
    overdue_days = (reference - last_maintenance).dt.days

    due = equipment.loc[overdue_days > days].copy()
    if due.empty:
        return pd.DataFrame(columns=columns)

    due["未保养天数"] = (
        reference - pd.to_datetime(due["last_maintenance"], errors="coerce")
    ).dt.days

    return (
        due.sort_values("未保养天数", ascending=False)
        .reset_index(drop=True)[columns]
    )


def equipment_insights(df=None, today=None):
    """生成驾驶舱「设备」模块的文字结论。"""
    equipment = load_equipment() if df is None else df
    if equipment.empty:
        return ["当前没有设备数据。"]

    summary = summarize_equipment(equipment, today=today)
    lines = [
        (
            f"设备总数 {summary['total_equipment']} 台，正常 {summary['normal_count']} 台，"
            f"异常 {summary['abnormal_count']} 台"
            f"（预警 {summary['warning_count']}、故障 {summary['fault_count']}）。"
        ),
        (
            f"设备正常率 {summary['normal_ratio']:.1%}，"
            f"异常设备对应日产能 {summary['abnormal_capacity']} 件。"
        ),
    ]

    if summary["maintenance_due_count"]:
        lines.append(
            f"有 {summary['maintenance_due_count']} 台设备超过 "
            f"{DEFAULT_MAINTENANCE_INTERVAL_DAYS} 天未保养，建议安排维保。"
        )

    return lines
