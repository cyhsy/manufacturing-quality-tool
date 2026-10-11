"""制造运营中心（A-02 ~ A-07）数据、工具与分析层测试。

覆盖内容：
- data/ 下新增模拟数据的字段与规模；
- tools/ 四个查询工具的返回与筛选行为（A-06）；
- modules/ 订单、设备、生产分析口径；
- 数据一致性：production.equipment 必须存在于 equipment.equipment_id；
- 质量分析复用：data/quality.csv 走原有 modules.quality_analysis 分析口径；
- app.py 已新增「制造运营中心」Tab 且语法有效。
"""

import ast
import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from modules import (
    equipment_analysis,
    order_analysis,
    production_analysis,
    quality_analysis,
)
from modules.equipment_analysis import (
    get_abnormal_equipment,
    get_maintenance_due,
    get_status_breakdown,
    summarize_equipment,
)
from modules.order_analysis import (
    get_priority_breakdown,
    get_urgent_orders,
    order_insights,
    summarize_orders,
)
from modules.production_analysis import (
    calculate_capacity_vs_demand,
    parse_yield_rate,
    summarize_production,
)
from tools import DATA_DIR
from tools.equipment_tool import query_equipment_status
from tools.inventory_tool import query_inventory
from tools.order_tool import query_orders
from tools.production_tool import query_production_capacity
from tools.quality_tool import query_quality_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 11)

NEW_DATA_FILES = {
    "orders.csv": ["order_id", "customer", "product", "quantity", "deadline", "priority"],
    "inventory.csv": ["material", "stock", "safety_stock", "unit"],
    "production.csv": ["product", "process", "equipment", "daily_capacity", "yield_rate", "status"],
    "equipment.csv": ["equipment_id", "equipment_type", "status", "capacity", "last_maintenance"],
    "iot_sensor.csv": ["timestamp", "equipment_id", "temperature", "vibration", "current", "status"],
    "quality.csv": list(quality_analysis.REQUIRED_COLUMNS),
}


# --------------------------------------------------------------------------
# A-01 / A-02 ~ A-05：数据文件
# --------------------------------------------------------------------------


@pytest.mark.parametrize("file_name,columns", sorted(NEW_DATA_FILES.items()))
def test_data_file_exists_with_required_columns(file_name, columns):
    path = DATA_DIR / file_name
    assert path.is_file(), f"缺少数据文件：{path}"

    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = [column for column in columns if column not in df.columns]
    assert missing == [], f"{file_name} 缺少字段：{missing}"
    assert not df.empty, f"{file_name} 不应为空"


def test_orders_csv_contains_documented_examples():
    orders = query_orders()
    first = orders.loc[orders["order_id"] == "O001"].iloc[0]
    assert first["customer"] == "新能源车企A"
    assert first["product"] == "电机壳体"
    assert int(first["quantity"]) == 10000
    assert first["deadline"] == "2026-11-01"
    assert first["priority"] == "high"

    second = orders.loc[orders["order_id"] == "O002"].iloc[0]
    assert second["product"] == "变速箱壳体"
    assert second["priority"] == "normal"


def test_inventory_and_equipment_csv_contain_documented_examples():
    inventory = query_inventory()
    aluminium = inventory.loc[inventory["material"] == "铝合金"].iloc[0]
    assert (int(aluminium["stock"]), int(aluminium["safety_stock"]), aluminium["unit"]) == (
        5000,
        3000,
        "kg",
    )

    equipment = query_equipment_status()
    cnc02 = equipment.loc[equipment["equipment_id"] == "CNC02"].iloc[0]
    assert cnc02["equipment_type"] == "CNC"
    assert cnc02["status"] == "warning"
    assert int(cnc02["capacity"]) == 600


# --------------------------------------------------------------------------
# A-06：数据读取工具
# --------------------------------------------------------------------------


def test_query_orders_returns_all_rows_and_filters():
    all_orders = query_orders()
    assert len(all_orders) == 15
    assert set(all_orders["priority"]) <= {"high", "normal", "low"}

    high_orders = query_orders(priority="high")
    assert len(high_orders) == 4
    assert set(high_orders["priority"]) == {"high"}

    multi = query_orders(priority=["high", "low"])
    assert len(multi) == 8

    by_product = query_orders(product="电机壳体")
    assert set(by_product["order_id"]) == {"O001", "O014"}

    sorted_orders = query_orders(sort_by_deadline=True)
    deadlines = list(sorted_orders["deadline"])
    assert deadlines == sorted(deadlines)

    assert query_orders(customer="不存在的客户").empty


def test_query_orders_supports_order_id_filter():
    single = query_orders(order_id="O001")
    assert list(single["order_id"]) == ["O001"]
    assert int(single.iloc[0]["quantity"]) == 10000

    assert list(query_orders(order_id="o001")["order_id"]) == ["O001"]
    assert sorted(query_orders(order_id=["O001", "O002"])["order_id"]) == ["O001", "O002"]
    assert query_orders(order_id="O999").empty


def test_query_inventory_returns_stock_and_shortage_subset():
    inventory = query_inventory()
    assert len(inventory) == 13
    assert {"material", "stock", "safety_stock", "unit"} <= set(inventory.columns)

    shortage = query_inventory(only_shortage=True)
    assert len(shortage) == 4
    assert (shortage["stock"] < shortage["safety_stock"]).all()
    assert set(shortage["material"]) == {"铸铁", "铜材", "焊丝", "刀具"}

    single = query_inventory(material="钢材")
    assert len(single) == 1
    assert int(single.iloc[0]["stock"]) == 8000


def test_query_equipment_status_returns_status_and_abnormal_subset():
    equipment = query_equipment_status()
    assert len(equipment) == 15

    abnormal = query_equipment_status(only_abnormal=True)
    assert len(abnormal) == 5
    assert set(abnormal["status"]) == {"warning", "fault"}

    faults = query_equipment_status(status="fault")
    assert list(faults["equipment_id"]) == ["WELD02"]

    single = query_equipment_status(equipment_id="CNC01")
    assert len(single) == 1
    assert single.iloc[0]["status"] == "normal"


def test_query_production_capacity_returns_capacity_and_running_subset():
    production = query_production_capacity()
    assert len(production) == 18

    running = query_production_capacity(only_running=True)
    assert len(running) == 14
    assert set(running["status"]) == {"running"}

    by_process = query_production_capacity(process="铸造")
    assert len(by_process) == 3

    assert query_production_capacity(product="不存在的产品").empty


def test_query_quality_data_reads_original_quality_dataset():
    quality = query_quality_data()
    assert not quality.empty
    assert set(quality_analysis.REQUIRED_COLUMNS) <= set(quality.columns)

    one_process = quality["工序"].iloc[0]
    filtered = query_quality_data(process=one_process)
    assert not filtered.empty
    assert set(filtered["工序"]) == {one_process}


# --------------------------------------------------------------------------
# 数据一致性
# --------------------------------------------------------------------------


def test_production_equipment_references_exist_in_equipment_master():
    production = query_production_capacity()
    equipment_ids = set(query_equipment_status()["equipment_id"])

    unknown = sorted(set(production["equipment"]) - equipment_ids)
    assert unknown == [], f"production.csv 引用了不存在的设备编号：{unknown}"


def test_iot_sensor_references_exist_in_equipment_master():
    sensors = pd.read_csv(DATA_DIR / "iot_sensor.csv", encoding="utf-8-sig")
    equipment_ids = set(query_equipment_status()["equipment_id"])

    unknown = sorted(set(sensors["equipment_id"]) - equipment_ids)
    assert unknown == [], f"iot_sensor.csv 引用了不存在的设备编号：{unknown}"


# --------------------------------------------------------------------------
# 分析层
# --------------------------------------------------------------------------


def test_summarize_orders_matches_data():
    summary = summarize_orders()

    assert summary["order_count"] == 15
    assert summary["total_quantity"] == 83500
    assert summary["customer_count"] == 10
    assert summary["high_priority_count"] == 4
    assert summary["earliest_deadline"] == date(2026, 11, 1)
    assert summary["latest_deadline"] == date(2026, 12, 10)

    breakdown = get_priority_breakdown()
    assert list(breakdown["优先级"]) == ["高", "普通", "低"]
    assert breakdown["订单数"].sum() == 15
    assert math.isclose(breakdown["占比"].sum(), 1.0, rel_tol=1e-9)


def test_urgent_orders_and_insights():
    urgent = get_urgent_orders(limit=3)
    assert len(urgent) == 3
    assert list(urgent["order_id"]) == ["O001", "O003", "O006"]

    insights = order_insights(today=TODAY)
    assert insights
    assert any("在手订单 15 单" in line for line in insights)
    assert not any("超过交付日期" in line for line in insights)


def test_summarize_equipment_matches_data():
    summary = summarize_equipment(today=TODAY)

    assert summary["total_equipment"] == 15
    assert summary["normal_count"] == 10
    assert summary["warning_count"] == 4
    assert summary["fault_count"] == 1
    assert summary["abnormal_count"] == 5
    raw_equipment = pd.read_csv(DATA_DIR / "equipment.csv", encoding="utf-8-sig")
    assert summary["total_capacity"] == int(raw_equipment["capacity"].sum())

    breakdown = get_status_breakdown()
    assert list(breakdown["设备状态"]) == ["正常", "预警", "故障"]
    assert breakdown["设备数量"].sum() == 15

    abnormal = get_abnormal_equipment()
    assert list(abnormal["equipment_id"])[0] == "WELD02"


def test_maintenance_due_flags_fault_and_warning_equipment():
    due = get_maintenance_due(today=TODAY)
    due_ids = set(due["equipment_id"])

    assert "WELD02" in due_ids
    assert (due["未保养天数"] > 60).all()


def test_summarize_production_matches_data():
    summary = summarize_production()

    assert summary["line_count"] == 18
    assert summary["product_count"] == 12
    assert summary["process_count"] == 9
    assert summary["equipment_count"] == 15
    assert summary["total_daily_capacity"] == 16450
    assert summary["running_line_count"] == 14
    assert summary["running_daily_capacity"] == 14300
    assert 0.95 < summary["average_yield_rate"] < 0.98
    # 停机产线的 0% 良率不应混入「在产平均良率」
    assert summary["average_yield_rate"] > summary["overall_average_yield_rate"]


def test_parse_yield_rate_accepts_percent_and_decimal():
    parsed = parse_yield_rate(pd.Series(["96%", "0.98", "100%", "0%", 0.5]))
    assert list(parsed.round(4)) == [0.96, 0.98, 1.0, 0.0, 0.5]


def test_capacity_vs_demand_uses_running_capacity():
    comparison = calculate_capacity_vs_demand(today=TODAY)

    assert comparison["total_demand"] == 83500
    assert comparison["daily_capacity"] == 14300
    assert comparison["required_days"] == math.ceil(83500 / 14300)
    assert comparison["earliest_deadline"] == date(2026, 11, 1)
    assert comparison["available_days"] == 21
    assert comparison["capacity_risk"] is False

    tight = calculate_capacity_vs_demand(today=date(2026, 10, 30))
    assert tight["available_days"] == 2
    assert tight["capacity_risk"] is True


def test_all_analysis_entry_points_used_by_cockpit_run():
    """驾驶舱调用的每个分析入口都必须能跑通并返回约定列。"""
    orders = query_orders()
    equipment = query_equipment_status()
    production = query_production_capacity()

    # 订单
    assert list(order_analysis.get_priority_breakdown(orders).columns) == [
        "优先级",
        "订单数",
        "总数量",
        "占比",
    ]
    assert len(order_analysis.get_urgent_orders(orders, limit=3)) == 3
    assert order_analysis.order_insights(orders, today=TODAY)
    assert list(order_analysis.to_display_frame(orders).columns) == [
        "订单编号",
        "客户",
        "产品",
        "数量",
        "交付日期",
        "优先级",
    ]

    # 设备
    assert list(equipment_analysis.get_status_breakdown(equipment).columns) == [
        "设备状态",
        "设备数量",
        "日产能合计",
        "占比",
    ]
    assert list(equipment_analysis.to_display_frame(equipment).columns) == [
        "设备编号",
        "设备类型",
        "状态",
        "日产能",
        "上次保养",
    ]
    assert equipment_analysis.equipment_insights(equipment, today=TODAY)

    # 生产（MES）
    process_breakdown = production_analysis.get_process_breakdown(production)
    assert list(process_breakdown.columns) == ["工序", "产线数量", "日产能合计", "平均良率"]
    assert len(process_breakdown) == 9
    assert process_breakdown["日产能合计"].sum() == 16450

    assert list(production_analysis.get_status_breakdown(production).columns) == [
        "产线状态",
        "产线数量",
        "日产能合计",
        "占比",
    ]
    assert list(production_analysis.to_display_frame(production).columns) == [
        "产品",
        "工序",
        "设备编号",
        "日产能",
        "良率",
        "产线状态",
    ]
    assert production_analysis.production_insights(
        orders_df=orders,
        production_df=production,
        today=TODAY,
    )


# --------------------------------------------------------------------------
# 质量分析复用（不破坏原有功能）
# --------------------------------------------------------------------------


def test_quality_overview_reuses_original_analysis():
    overview = quality_analysis.analyze_quality_overview()

    assert overview["missing_columns"] == []
    assert overview["record_count"] > 0
    assert overview["total_defect_count"] > 0
    assert overview["defect_type_count"] > 0
    assert list(overview["defect_summary"].columns) == ["缺陷类型", "缺陷数量", "占比"]
    assert overview["summary_lines"]
    assert any("数据总览" in line for line in overview["summary_lines"])


def test_quality_data_matches_packaged_sample_dataset():
    quality = quality_analysis.load_quality_dataframe()
    sample = pd.read_csv(
        PROJECT_ROOT / "sample_data" / "质量异常记录样本.csv",
        encoding="utf-8-sig",
    )
    pd.testing.assert_frame_equal(quality, sample)


# --------------------------------------------------------------------------
# A-07：app.py 新增制造运营中心 Tab
# --------------------------------------------------------------------------


def test_app_py_declares_manufacturing_operations_tab():
    app_path = PROJECT_ROOT / "app.py"
    source = app_path.read_text(encoding="utf-8")

    ast.parse(source)  # 语法必须有效

    for token in [
        "制造运营中心",
        "show_manufacturing_overview",
        "show_quality_analysis_page",
        "query_orders",
        "query_inventory",
        "query_equipment_status",
        "query_production_capacity",
        "analyze_quality_overview",
    ]:
        assert token in source, f"app.py 缺少：{token}"

    assert "from src." not in source, "app.py 仍引用旧的 src. 包"
