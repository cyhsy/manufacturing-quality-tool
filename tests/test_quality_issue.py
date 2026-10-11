"""S4-A 测试：质量议题分析 / 质量追溯 / 质量改善知识库 / Supervisor 接入。

覆盖：
- S4-A-03 知识库：≥20 条、覆盖四类缺陷、与数据集缺陷类型对齐、检索打分；
- S4-A-02 追溯：产品 / 批次 / 缺陷 -> 工序 -> 设备 -> 生产记录；
- S4-A-01 议题分析：产品/缺陷/时间、环比窗口、恶化维度、改善建议；
- S4-A-04 Supervisor：新能力 quality_issue_analysis 与质量侧实体路由。
"""

import json
from pathlib import Path

import pytest

from agent_tools import quality_tools
from agents import quality_agent, supervisor_agent
from modules import quality_issue_analysis, quality_knowledge
from tools import traceability_tool
from tools.quality_tool import list_defect_types


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = PROJECT_ROOT / "knowledge" / "quality"


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY，避免规划类测试意外发起真实 LLM 调用。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


# --------------------------------------------------------------------------
# S4-A-03 质量改善知识库
# --------------------------------------------------------------------------


def test_quality_knowledge_base_covers_four_categories():
    cases = quality_knowledge.load_quality_cases()
    assert len(cases) >= 20, "质量改善知识库至少需要 20 条"

    categories = quality_knowledge.list_categories(cases)
    for expected in ("尺寸异常", "表面缺陷", "铸造缺陷", "装配异常"):
        assert categories.get(expected, 0) >= 1, f"缺少类别：{expected}"

    for case in cases:
        assert case["案例编号"].startswith("QI-"), case
        assert case["类别"] in quality_knowledge.CATEGORIES, case
        assert case["关联缺陷"], f"{case['标题']} 缺少关联缺陷"
        assert case["现象"], f"{case['标题']} 缺少现象"
        assert case["原因"], f"{case['标题']} 缺少原因"
        assert case["验证方法"], f"{case['标题']} 缺少验证方法"
        assert case["改善措施"], f"{case['标题']} 缺少改善措施"


def test_quality_knowledge_matches_every_dataset_defect_type():
    """数据集里的缺陷类型都应能在知识库中找到改善案例。"""
    known = {value for case in quality_knowledge.load_quality_cases() for value in case["关联缺陷"]}
    for defect_type in list_defect_types():
        assert defect_type in known, f"知识库缺少缺陷类型：{defect_type}"


def test_quality_knowledge_search_scores_defect_and_process():
    matches = quality_knowledge.search_quality_knowledge({"缺陷类型": "尺寸偏大", "工序": "铣削"})

    assert matches
    top = matches[0]
    assert top["标题"] == "尺寸偏大"
    assert top["score"] == 5.0
    assert 0 < top["confidence"] <= 1
    assert set(top["命中依据"]) == {"关联缺陷命中：尺寸偏大", "适用工序命中：铣削"}


def test_quality_knowledge_requires_defect_match():
    """仅命中工序（2.0 分）不足以成为改善建议。"""
    assert quality_knowledge.search_quality_knowledge({"工序": "铣削"}) == []

    without_defect = quality_knowledge.search_quality_knowledge({"类别": "尺寸异常"})
    assert without_defect == []


# --------------------------------------------------------------------------
# S4-A-02 质量追溯
# --------------------------------------------------------------------------


def test_traceability_by_defect_links_process_equipment_and_production():
    trace = traceability_tool.query_traceability(defect="尺寸偏大")

    assert trace["record_count"] == 16
    assert trace["total_defect_quantity"] == 140
    assert trace["defect_rate"] > 0
    assert set(trace["processes"]) == {"热处理", "表面处理", "装配", "钻孔", "铣削"}
    # MES 无对应工序的工序必须显式列出，不静默丢弃
    assert trace["unmatched_processes"] == ["表面处理"]

    equipment_ids = {item["设备编号"] for item in trace["equipment"]}
    assert {"CNC01", "CNC02", "CNC03", "HEAT01", "DRILL01", "ASSY01", "ASSY02"} <= equipment_ids
    for item in trace["equipment"]:
        assert item["关联工序"]
        assert item["MES工序"]
        assert item["设备状态"] in {"normal", "warning", "fault"}
        assert "最新传感器" in item

    # iot_sensor.csv 只覆盖部分设备：已装传感器的设备带回读数，未装的显式为 None
    sensors = {item["设备编号"]: item["最新传感器"] for item in trace["equipment"]}
    assert sensors["CNC02"]["status"] == "alarm"
    assert sensors["CNC02"]["temperature"] == 71.5
    assert sensors["CNC01"]["status"] == "normal"
    assert sensors["ASSY01"] is None

    assert trace["production_records"]
    for record in trace["production_records"]:
        assert {"追溯工序", "产品", "工序", "设备", "日产能", "良率", "产线状态"} <= set(record)


def test_traceability_by_product_and_batch():
    by_product = traceability_tool.query_traceability(product="支架")
    assert by_product["record_count"] == 19
    assert "铣削" in by_product["processes"]

    by_batch = traceability_tool.query_traceability(batch="LOT-202605-001")
    assert by_batch["record_count"] == 1
    assert by_batch["total_defect_quantity"] == 8
    assert by_batch["processes"] == ["铣削"]

    assert traceability_tool.query_traceability(product="不存在的零件")["record_count"] == 0


def test_traceability_limits_detail_but_keeps_full_statistics():
    trace = traceability_tool.query_traceability(defect="尺寸偏大", record_limit=3)

    assert len(trace["quality_records"]) == 3
    assert trace["record_count"] == 16
    assert trace["total_defect_quantity"] == 140


def test_traceability_tool_reads_only_through_tools_layer():
    source = (PROJECT_ROOT / "tools" / "traceability_tool.py").read_text(encoding="utf-8")

    assert "read_csv" not in source
    assert "from tools." in source


# --------------------------------------------------------------------------
# S4-A-01 质量议题分析
# --------------------------------------------------------------------------


def test_issue_analysis_default_window_is_half_of_data_span():
    issue = quality_agent.analyze_quality_issue()
    window = issue["scope"]["window"]

    assert window["days"] == 15
    assert window["reference"] == "2026-05-14"
    assert window["recent_start"] == "2026-04-30"
    assert window["recent_end"] == "2026-05-14"
    assert window["previous_start"] == "2026-04-15"
    assert window["previous_end"] == "2026-04-29"


def test_issue_analysis_reports_flat_overall_but_worsened_dimensions():
    """数据真相：整体缺陷率环比持平，但部分维度明显恶化，结论必须如实。"""
    issue = quality_agent.analyze_quality_issue()
    trend = issue["trend"]

    assert trend["verdict"] == "持平"
    assert issue["metrics"]["record_count"] == 49
    assert issue["metrics"]["defect_quantity"] == 398
    assert round(issue["metrics"]["defect_rate"], 5) == 0.03996
    assert round(trend["previous"]["defect_rate"], 5) == 0.04
    assert abs(trend["rate_change_ratio"]) < 0.05

    worsened = {
        item["名称"]: (item["上期缺陷"], item["本期缺陷"])
        for item in trend["worsened_dimensions"]
    }
    assert worsened["尺寸偏大"] == (38, 102)
    assert worsened["热处理"] == (21, 68)

    improved = {item["名称"] for item in trend["improved_dimensions"]}
    assert "尺寸偏小" in improved

    assert issue["risk"] == "medium"
    assert any("环比恶化维度" in line for line in issue["findings"])
    assert any("质量持平" in line for line in issue["findings"])


def test_issue_analysis_includes_traceability_and_improvements():
    issue = quality_agent.analyze_quality_issue()

    trace = issue["traceability"]
    assert trace["record_count"] > 0
    assert trace["equipment"]
    assert trace["production_records"]
    assert "表面处理" in trace["unmatched_processes"]

    assert issue["improvements"]
    top = issue["improvements"][0]
    assert top["缺陷类型"] == "尺寸偏大"
    assert top["案例编号"] == "QI-001"
    assert top["改善措施"] and top["验证方法"] and top["原因"]
    assert issue["knowledge_base_size"] >= 20


def test_issue_analysis_scoped_by_product_defect_and_batch():
    issue = quality_agent.analyze_quality_issue(
        product="支架", defect_type="尺寸偏大", batch="LOT-202605-001"
    )

    assert issue["metrics"]["record_count"] == 1
    assert issue["metrics"]["defect_quantity"] == 8
    assert issue["scope"]["product"] == "支架"
    assert issue["scope"]["defect_type"] == "尺寸偏大"
    assert issue["scope"]["batch"] == "LOT-202605-001"
    assert any("样本量较小" in line for line in issue["findings"])


def test_issue_analysis_with_explicit_time_range():
    issue = quality_agent.analyze_quality_issue(start="2026-05-01", end="2026-05-14")
    window = issue["scope"]["window"]

    assert window["days"] == 14
    assert window["recent_start"].startswith("2026-05-01")
    assert window["recent_end"].startswith("2026-05-14")


def test_issue_analysis_without_matching_records():
    issue = quality_agent.analyze_quality_issue(product="不存在的零件")

    assert issue["risk"] == "unknown"
    assert issue["traceability"] is None
    assert issue["improvements"] == []
    json.dumps(issue, ensure_ascii=False)


def test_issue_analysis_window_and_summary_helpers():
    records = quality_tools.get_issue_records()

    window = quality_issue_analysis.resolve_window(records)
    assert window["days"] == 15

    explicit = quality_issue_analysis.resolve_window(records, days=30)
    assert explicit["days"] == 30
    assert explicit["recent_start"] == "2026-04-15"
    assert explicit["recent_end"] == "2026-05-14"

    summary = quality_issue_analysis.summarize_records(records)
    assert summary["record_count"] == 100
    assert summary["defect_quantity"] == 820
    assert summary["batch_quantity"] == 20510
    assert summary["defect_type_count"] == 7
    assert summary["top_defect_type"] == "尺寸偏小"


# --------------------------------------------------------------------------
# S4-A-04 Supervisor 接入
# --------------------------------------------------------------------------


def test_supervisor_routes_quality_decline_to_quality_agent():
    plan = supervisor_agent.build_plan("最近质量下降，帮我分析")

    assert plan["intent_code"] == "quality_issue_analysis"
    assert plan["capabilities"] == ["quality_issue_analysis"]

    step = plan["steps"][0]
    assert step["agent"] == "quality_agent"
    assert step["action"] == "analyze_quality_issue"


def test_supervisor_executes_quality_issue_analysis():
    outcome = supervisor_agent.handle("最近质量下降，帮我分析")

    assert set(outcome["results"]) == {"quality_agent"}
    result = outcome["results"]["quality_agent"]
    assert result["status"] == "ok"
    assert result["capabilities"] == ["quality_issue_analysis"]
    assert result["trend"]["verdict"] == "持平"
    assert result["traceability"]["equipment"]
    assert result["improvements"]

    sections = outcome["risk_report"]["sections"]
    assert [section["title"] for section in sections] == ["质量议题风险"]
    assert sections[0]["risk"] in {"low", "medium", "high"}

    json.dumps(outcome, ensure_ascii=False)


def test_supervisor_quality_entity_routing():
    plan = supervisor_agent.build_plan("支架尺寸偏大问题，批次LOT-202605-001")

    assert plan["intent_code"] == "quality_issue_analysis"
    assert plan["entities"]["part_name"] == "支架"
    assert plan["entities"]["defect_type"] == "尺寸偏大"
    assert plan["entities"]["batch"] == "LOT-202605-001"
    assert plan["steps"][0]["arguments"] == {
        "part_name": "支架",
        "defect_type": "尺寸偏大",
        "batch": "LOT-202605-001",
    }


def test_quality_overview_routing_is_unchanged():
    """回归：普通质量问询仍走质量总览，不被议题分析抢走。"""
    plan = supervisor_agent.build_plan("看看质量缺陷情况")

    assert plan["intent_code"] == "quality_query"
    assert plan["capabilities"] == ["quality"]


def test_part_name_is_not_extracted_from_product_name():
    """回归：「涡轮支架」是产品名，不应被识别成零件「支架」。"""
    entities = supervisor_agent.extract_entities("2000件涡轮支架，2周内交付")

    assert entities["product"] == "涡轮支架"
    assert entities["part_name"] is None


def test_quality_agent_overview_capability_is_unchanged():
    result = quality_agent.run(capabilities=["quality"])

    assert result["status"] == "ok"
    assert result["metrics"]["total_defects"] == 820
    assert result["summary_lines"]
