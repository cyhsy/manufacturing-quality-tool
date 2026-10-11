"""质量追溯工具（S4-A-02）。

根据 **产品 / 批次 / 缺陷**（可选：工序、时间范围）查询关联链路：

    data/quality.csv（质量记录：零件名称 / 零件编号 / 批次号 / 工序 / 缺陷类型）
        ↓ 过滤
    涉及工序
        ↓ 工序标准化（PROCESS_EQUIVALENCE）
    data/production.csv（关联生产记录：产品 / 工序 / 设备 / 日产能 / 良率 / 状态）
        ↓ 设备编号
    data/equipment.csv + data/iot_sensor.csv（设备状态与最新传感器读数）

数据现状说明（决定关联方式）：

- ``quality.csv`` 的「零件名称」与 MES ``production.csv`` 的「产品」**没有交集**，
  因此产品维度只在质量侧过滤；跨系统关联以「工序」为纽带；
- MES 中找不到对应产线的工序（例如「表面处理」）会在 ``unmatched_processes``
  中显式列出，不做静默丢弃。
"""

import pandas as pd

from tools.equipment_tool import query_equipment_status
from tools.iot_sensor_tool import query_latest_sensor_reading
from tools.production_tool import query_production_capacity
from tools.quality_tool import (
    BATCH_COLUMN,
    PART_CODE_COLUMN,
    PART_NAME_COLUMN,
    PROCESS_COLUMN,
    query_quality_data,
)


# 质量侧工序名 -> MES 侧工序名（空的元组表示 MES 无对应工序）
PROCESS_EQUIVALENCE = {
    "车削": ("车削",),
    "铣削": ("CNC加工",),
    "钻孔": ("钻削",),
    "热处理": ("热处理",),
    "装配": ("装配",),
    "表面处理": (),
}

TRACE_COLUMNS = [
    "日期",
    "批次号",
    "零件编号",
    "零件名称",
    "工序",
    "缺陷类型",
    "缺陷数量",
    "批次数量",
    "供应商",
    "责任部门",
    "严重等级",
    "处理状态",
]


def _to_int(value):
    number = pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0).iloc[0]
    return int(number)


def filter_quality_records(product=None, batch=None, defect=None, process=None, start=None, end=None):
    """按查询条件过滤质量记录（质量侧统一的过滤口径，供追溯与议题分析共用）。"""
    records = query_quality_data(process=process, defect_type=defect)

    if product is not None:
        target = str(product)
        by_name = records[PART_NAME_COLUMN].astype(str).str.contains(target, case=False, regex=False)
        by_code = records[PART_CODE_COLUMN].astype(str).str.contains(target, case=False, regex=False)
        records = records.loc[by_name | by_code]

    if batch is not None:
        target = str(batch)
        records = records.loc[
            records[BATCH_COLUMN].astype(str).str.contains(target, case=False, regex=False)
        ]

    if start is not None or end is not None:
        dates = pd.to_datetime(records["日期"], errors="coerce")
        if start is not None:
            records = records.loc[dates >= pd.Timestamp(start)]
        if end is not None:
            records = records.loc[dates <= pd.Timestamp(end)]

    return records


def _link_production(quality_processes):
    """质量工序 -> MES 生产记录 / 设备关联。"""
    production = query_production_capacity()

    production_records = []
    unmatched_processes = []
    seen_lines = set()

    for quality_process in quality_processes:
        mes_processes = PROCESS_EQUIVALENCE.get(quality_process, (quality_process,))
        if not mes_processes:
            unmatched_processes.append(quality_process)
            continue

        lines = production.loc[production["process"].astype(str).isin(mes_processes)]
        if lines.empty:
            unmatched_processes.append(quality_process)
            continue

        for _, line in lines.iterrows():
            key = (str(line["product"]), str(line["process"]), str(line["equipment"]))
            if key in seen_lines:
                continue
            seen_lines.add(key)
            production_records.append(
                {
                    "追溯工序": quality_process,
                    "产品": str(line["product"]),
                    "工序": str(line["process"]),
                    "设备": str(line["equipment"]),
                    "日产能": _to_int(line["daily_capacity"]),
                    "良率": str(line["yield_rate"]),
                    "产线状态": str(line["status"]),
                }
            )

    return production_records, sorted(set(unmatched_processes))


def _link_equipment(production_records):
    """生产记录 -> 设备台账状态 + 最新传感器读数。"""
    master = query_equipment_status()
    master_by_id = {str(row["equipment_id"]): row for _, row in master.iterrows()}

    links = {}
    for record in production_records:
        equipment_id = record["设备"]
        entry = links.setdefault(
            equipment_id,
            {
                "设备编号": equipment_id,
                "关联工序": [],
                "MES工序": [],
                "设备类型": "",
                "设备状态": "unknown",
                "设备日产能": 0,
                "最新传感器": None,
            },
        )
        if record["追溯工序"] not in entry["关联工序"]:
            entry["关联工序"].append(record["追溯工序"])
        if record["工序"] not in entry["MES工序"]:
            entry["MES工序"].append(record["工序"])

    for equipment_id, entry in links.items():
        row = master_by_id.get(equipment_id)
        if row is not None:
            entry["设备类型"] = str(row["equipment_type"])
            entry["设备状态"] = str(row["status"])
            entry["设备日产能"] = _to_int(row["capacity"])
        entry["最新传感器"] = query_latest_sensor_reading(equipment_id)

    return sorted(links.values(), key=lambda item: item["设备编号"])


def query_traceability(
    product=None,
    batch=None,
    defect=None,
    process=None,
    start=None,
    end=None,
    record_limit=20,
):
    """质量追溯查询。

    参数：
        product: 产品（匹配质量数据的零件名称或零件编号，包含匹配）。
        batch:   批次号（包含匹配，如 ``LOT-202605``）。
        defect:  缺陷类型（精确匹配）。
        process: 工序（精确匹配）。
        start/end: 日期范围（含端点）。
        record_limit: 明细返回条数上限（统计值仍按全部命中记录计算）。

    返回 dict：
        query, record_count, total_defect_quantity, total_batch_quantity,
        defect_rate, date_range, processes, quality_records,
        production_records, equipment, unmatched_processes
    """
    records = filter_quality_records(product, batch, defect, process, start, end)

    total_defects = _to_int(pd.to_numeric(records["缺陷数量"], errors="coerce").sum()) if not records.empty else 0
    total_batches = _to_int(pd.to_numeric(records["批次数量"], errors="coerce").sum()) if not records.empty else 0

    dates = pd.to_datetime(records["日期"], errors="coerce").dropna() if not records.empty else pd.Series(dtype="datetime64[ns]")
    date_range = (
        [dates.min().date().isoformat(), dates.max().date().isoformat()]
        if not dates.empty
        else None
    )

    quality_processes = (
        sorted({str(value) for value in records[PROCESS_COLUMN]}) if not records.empty else []
    )

    production_records, unmatched_processes = _link_production(quality_processes)
    equipment = _link_equipment(production_records)

    detail = records if record_limit is None or record_limit <= 0 else records.head(record_limit)
    detail_columns = [column for column in TRACE_COLUMNS if column in detail.columns]

    return {
        "query": {
            "product": product,
            "batch": batch,
            "defect": defect,
            "process": process,
            "start": None if start is None else str(start),
            "end": None if end is None else str(end),
        },
        "record_count": int(len(records)),
        "total_defect_quantity": total_defects,
        "total_batch_quantity": total_batches,
        "defect_rate": (total_defects / total_batches) if total_batches else 0.0,
        "date_range": date_range,
        "processes": quality_processes,
        "quality_records": detail[detail_columns].to_dict(orient="records"),
        "production_records": production_records,
        "equipment": equipment,
        "unmatched_processes": unmatched_processes,
    }
