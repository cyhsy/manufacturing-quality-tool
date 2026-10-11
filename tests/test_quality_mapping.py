"""S4.1 测试：质量意图优先级 / 产品映射层 / 追溯输出 / 订单关联。

覆盖：
- S4.1-A-01 「良率下降」等组合说法必须路由到 quality_issue_analysis，且不破坏既有路由；
- S4.1-A-02 data/product_mapping.csv：字段、示例行、对 MES 产品与质量零件的覆盖；
- S4.1-A-03 追溯输出新增 original_product / mapped_quality_parts / mapping_source；
- S4.1-A-04 质量异常 -> 生产设备 -> 影响产品 -> 订单交付风险。
"""

import json
from pathlib import Path

import pytest

from agents import quality_agent, supervisor_agent
from tools import traceability_tool
from tools.production_tool import query_production_capacity


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = PROJECT_ROOT / "data" / "product_mapping.csv"


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY，避免规划类测试意外发起真实 LLM 调用。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


# --------------------------------------------------------------------------
# S4.1-A-01 质量意图优先级
# --------------------------------------------------------------------------


def test_yield_decline_routes_to_quality_issue_analysis():
    """S4.1-A-01 验收输入：最近电机壳体良率下降，分析原因。"""
    plan = supervisor_agent.build_plan("最近电机壳体良率下降，分析原因")

    assert plan["intent_code"] == "quality_issue_analysis"
    assert plan["capabilities"] == ["quality_issue_analysis"]
    assert plan["entities"]["product"] == "电机壳体"

    step = plan["steps"][0]
    assert step["agent"] == "quality_agent"
    assert step["action"] == "analyze_quality_issue"
    assert step["arguments"] == {"product": "电机壳体"}


@pytest.mark.parametrize(
    "text",
    [
        "良率下降",
        "合格率下滑",
        "尺寸异常",
        "质量变差",
        "缺陷率上升",
        "电机壳体毛刺超标",
    ],
)
def test_quality_decline_synonyms_route_to_quality_issue_analysis(text):
    """组合判定（质量域词 + 趋势词）覆盖「良率/合格率/尺寸/毛刺」等说法。"""
    assert supervisor_agent.build_plan(text)["intent_code"] == "quality_issue_analysis"


def test_quality_decline_rule_needs_both_domain_and_decline_words():
    """只有趋势词没有质量域词时不应误判为质量议题。"""
    assert supervisor_agent.build_plan("今天产量下降")["intent_code"] != "quality_issue_analysis"


def test_existing_routing_is_not_broken_by_new_priority():
    """回归：质量总览 / 混合问询 / 订单 / 设备 / 库存路由保持不变。"""
    assert supervisor_agent.build_plan("看看质量缺陷情况")["intent_code"] == "quality_query"

    mixed = supervisor_agent.build_plan("设备有没有故障，顺便看下质量缺陷")
    assert mixed["intent_code"] == "mixed_query"
    assert set(mixed["capabilities"]) == {"equipment", "quality"}

    assert (
        supervisor_agent.build_plan("分析订单O001能否按时完成")["intent_code"]
        == "order_delivery"
    )
    assert (
        supervisor_agent.build_plan("CNC02报警了，帮我分析")["intent_code"]
        == "equipment_failure"
    )
    assert supervisor_agent.build_plan("库存够吗")["intent_code"] == "inventory_query"
    assert supervisor_agent.build_plan("今天工厂什么情况")["intent_code"] == "overview"


# --------------------------------------------------------------------------
# S4.1-A-02 产品映射层
# --------------------------------------------------------------------------


def test_product_mapping_file_has_documented_schema_and_example():
    assert MAPPING_PATH.is_file()

    mapping = traceability_tool.load_product_mapping()
    assert list(mapping.columns) == ["mes_product", "quality_part", "mapping_reason"]

    row = mapping.loc[mapping["mes_product"] == "电机壳体"].iloc[0]
    assert row["quality_part"] == "支架"
    assert row["mapping_reason"] == "MES产品质量由关键零件表征"


def test_product_mapping_covers_all_mes_products_and_quality_parts():
    mapping = traceability_tool.load_product_mapping()

    mes_products = set(query_production_capacity()["product"])
    quality_parts = set(traceability_tool.list_part_names())

    assert mes_products <= set(mapping["mes_product"])
    assert quality_parts <= set(mapping["quality_part"])
    assert mapping["mapping_reason"].astype(str).str.len().gt(0).all()


def test_resolve_quality_parts_by_mes_product_and_direct_part():
    by_product = traceability_tool.resolve_quality_parts("电机壳体")
    assert by_product["original_product"] == "电机壳体"
    assert by_product["mapped_quality_parts"] == ["支架", "法兰盘"]
    assert by_product["mapping_source"] == "product_mapping.csv"
    assert by_product["mapping_reason"]

    direct = traceability_tool.resolve_quality_parts("支架")
    assert direct["mapped_quality_parts"] == ["支架"]
    assert direct["mapping_source"] == "direct_quality_part"

    unknown = traceability_tool.resolve_quality_parts("不存在的零件")
    assert unknown["mapped_quality_parts"] == []
    assert unknown["mapping_source"] == "contains_match"

    assert traceability_tool.resolve_quality_parts(None)["mapping_source"] is None

    # 反向映射：质量零件 -> MES 产品
    assert traceability_tool.map_quality_parts_to_products(["支架"]) == ["涡轮支架", "电机壳体"]
    assert traceability_tool.map_quality_parts_to_products([]) == []


# --------------------------------------------------------------------------
# S4.1-A-03 追溯输出增加映射字段
# --------------------------------------------------------------------------


def test_traceability_reports_product_mapping_fields():
    trace = traceability_tool.query_traceability(product="电机壳体")

    assert trace["original_product"] == "电机壳体"
    assert trace["mapped_quality_parts"] == ["支架", "法兰盘"]
    assert trace["mapping_source"] == "product_mapping.csv"
    assert trace["mapping_reason"]

    # 命中的质量记录必须落在映射出的质量零件范围内
    parts = {record["零件名称"] for record in trace["quality_records"]}
    assert parts <= set(trace["mapped_quality_parts"])
    assert trace["record_count"] == 33
    assert trace["total_defect_quantity"] == 333
    assert trace["unmatched_processes"] == ["表面处理"]


def test_traceability_mapping_does_not_change_direct_quality_part_queries():
    """回归：直接按质量零件查询时行为与 S4 一致。"""
    trace = traceability_tool.query_traceability(product="支架")

    assert trace["mapping_source"] == "direct_quality_part"
    assert trace["mapped_quality_parts"] == ["支架"]
    assert trace["record_count"] == 19


def test_traceability_unknown_product_falls_back_to_contains_match():
    trace = traceability_tool.query_traceability(product="法兰")

    assert trace["mapping_source"] == "contains_match"
    assert trace["record_count"] > 0


# --------------------------------------------------------------------------
# S4.1-A-04 质量异常 -> 设备 -> 影响产品 -> 订单风险
# --------------------------------------------------------------------------


def test_issue_analysis_accepts_mes_product_via_mapping():
    """S4.1 验收链路：MES 产品 -> 产品映射 -> 质量对象 -> 缺陷 -> 工序 -> 设备。"""
    issue = quality_agent.analyze_quality_issue(product="电机壳体")

    assert issue["scope"]["product"] == "电机壳体"
    assert issue["traceability"]["mapped_quality_parts"] == ["支架", "法兰盘"]
    assert issue["traceability"]["mapping_source"] == "product_mapping.csv"
    assert issue["metrics"]["record_count"] == 21
    assert issue["improvements"]


def test_affected_orders_are_linked_from_quality_anomaly():
    issue = quality_agent.analyze_quality_issue(product="电机壳体")
    affected = issue["affected_orders"]

    assert "电机壳体" in affected["primary_products"]
    assert affected["equipment_products"]
    assert affected["order_count"] > 0
    assert affected["order_count"] == len(affected["orders"]) or affected["order_count"] >= len(
        affected["orders"]
    )

    # 订单按风险严重度排序
    ranks = [quality_agent.RISK_RANK[order["risk"]] for order in affected["orders"]]
    assert ranks == sorted(ranks)

    for order in affected["orders"]:
        assert order["order_id"].startswith("O")
        assert order["risk"] in {"low", "medium", "high", "unknown"}
        assert order["reason"]
        assert order["relation"] in {"直接映射", "共享设备"}

    # 电机壳体的在手订单属「直接映射」；共享设备的订单也会被纳入
    relations = {order["order_id"]: order["relation"] for order in affected["orders"]}
    assert relations["O001"] == "直接映射"
    assert relations["O014"] == "直接映射"
    assert "O002" in affected["affected_order_ids"]

    assert affected["delivery_risk"] in {"low", "medium", "high"}
    assert "order_tools.get_orders" in affected["risk_source"]
    json.dumps(affected, ensure_ascii=False)


def test_combined_risk_is_worst_of_quality_and_order_risk():
    issue = quality_agent.analyze_quality_issue(product="电机壳体")
    affected = issue["affected_orders"]

    assert issue["combined_risk"] == quality_agent._max_risk(
        issue["risk"], affected["delivery_risk"]
    )
    assert any("影响订单" in line for line in issue["findings"])


def test_affected_orders_handle_missing_traceability():
    result = quality_agent.assess_affected_orders(None)

    assert result["order_count"] == 0
    assert result["orders"] == []
    assert result["delivery_risk"] == "unknown"


def test_supervisor_end_to_end_for_yield_decline():
    outcome = supervisor_agent.handle("最近电机壳体良率下降，分析原因")

    assert set(outcome["results"]) == {"quality_agent"}

    result = outcome["results"]["quality_agent"]
    assert result["capabilities"] == ["quality_issue_analysis"]
    assert result["traceability"]["mapped_quality_parts"] == ["支架", "法兰盘"]
    assert result["affected_orders"]["order_count"] > 0
    assert result["affected_orders"]["affected_order_ids"]

    sections = outcome["risk_report"]["sections"]
    assert [section["title"] for section in sections] == ["质量议题风险"]
    assert sections[0]["risk"] in {"low", "medium", "high"}

    json.dumps(outcome, ensure_ascii=False)
