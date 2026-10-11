"""S3-A 测试：设备知识库 / 故障诊断 / 维修工单 / Supervisor 接入。

覆盖：
- S3-A-01 知识库：案例数量、字段完整性、任务书示例文件；
- S3-A-02 Equipment Agent：异常检测 + 故障诊断 + S3-A-02 约定输出；
- S3-A-03 维修工单：create_work_order() 六要素、编号递增、优先级/负责人规则、落库；
- S3-A-04 Supervisor：新能力 equipment_failure 与设备编号实体路由。
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from agent_tools import equipment_tools, work_order_tools
from agents import equipment_agent, supervisor_agent
from modules import equipment_knowledge
from tools.iot_sensor_tool import query_latest_sensor_reading, query_sensor_readings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = PROJECT_ROOT / "knowledge" / "equipment"

# S3-A-02 约定的诊断输出字段
DIAGNOSIS_KEYS = {"equipment", "status", "fault", "confidence", "recommendation"}
WORK_ORDER_REQUIRED_FIELDS = ("维修编号", "设备", "故障", "优先级", "负责人", "建议时间")


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY，避免规划类测试意外发起真实 LLM 调用。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


# --------------------------------------------------------------------------
# S3-A-01 设备故障知识库
# --------------------------------------------------------------------------


def test_knowledge_base_has_at_least_20_cases():
    cases = equipment_knowledge.load_equipment_cases()

    assert len(cases) >= 20, "设备故障知识库至少需要 20 条案例"
    for case in cases:
        assert case["案例编号"].startswith("EQ-"), case
        assert case["标题"], case
        assert case["现象"], f"{case['标题']} 缺少现象"
        assert case["可能原因"], f"{case['标题']} 缺少可能原因"
        assert case["处理"], f"{case['标题']} 缺少处理"
        assert case["优先级"] in {"高", "中", "低"}, case


def test_documented_example_case_exists():
    """任务书示例：主轴温升异常.md 的现象/原因/处理必须存在。"""
    path = KB_DIR / "主轴温升异常.md"
    assert path.is_file(), "缺少任务书示例案例：主轴温升异常.md"

    text = path.read_text(encoding="utf-8")
    for token in [
        "现象:",
        "温度>90℃",
        "可能原因:",
        "轴承磨损",
        "润滑不足",
        "处理:",
        "检查润滑系统",
        "更换轴承",
    ]:
        assert token in text, f"示例案例缺少：{token}"

    case = equipment_knowledge.parse_case(text, fallback_title="主轴温升异常")
    assert case["案例编号"] == "EQ-001"
    assert "轴承磨损" in case["可能原因"]
    assert "更换轴承" in case["处理"]


def test_knowledge_search_ranks_temperature_case_first():
    matches = equipment_knowledge.search_equipment_knowledge(
        {"温度": 95, "equipment_status": "warning", "equipment_type": "CNC"}
    )

    assert matches, "温度 95℃ 应命中温升类案例"
    assert matches[0]["标题"] == "主轴温升异常"
    assert 0 < matches[0]["confidence"] <= 1
    assert matches[0]["命中依据"]

    scores = [item["score"] for item in matches]
    assert scores == sorted(scores, reverse=True)


def test_knowledge_search_returns_nothing_for_healthy_equipment():
    matches = equipment_knowledge.search_equipment_knowledge(
        {
            "温度": 42.8,
            "振动": 1.2,
            "电流": 12.6,
            "equipment_status": "normal",
            "sensor_status": "normal",
            "equipment_type": "CNC",
        }
    )

    assert matches == []


def test_knowledge_confidence_is_capped_similarity():
    matches = equipment_knowledge.search_equipment_knowledge(
        {"温度": 95, "equipment_status": "warning", "equipment_type": "CNC"}
    )

    assert all(0 <= item["confidence"] <= equipment_knowledge.CONFIDENCE_CAP for item in matches)
    assert all(item["confidence"] <= 1 for item in matches)


# --------------------------------------------------------------------------
# 传感器数据访问工具
# --------------------------------------------------------------------------


def test_iot_sensor_tool_reads_latest_reading():
    readings = query_sensor_readings(equipment_id="CNC02")
    assert len(readings) == 5
    assert list(readings["timestamp"]) == sorted(readings["timestamp"])

    latest = query_latest_sensor_reading("CNC02")
    assert latest["equipment_id"] == "CNC02"
    assert latest["temperature"] == 71.5
    assert latest["vibration"] == 6.2
    assert latest["status"] == "alarm"

    assert query_latest_sensor_reading("XXX99") is None

    alarms = query_sensor_readings(equipment_id="CNC02", only_alarm=True)
    assert not alarms.empty
    assert set(alarms["status"]) <= {"warning", "alarm"}


# --------------------------------------------------------------------------
# S3-A-02 Equipment Agent：异常检测 + 故障诊断
# --------------------------------------------------------------------------


def test_diagnose_equipment_matches_s3_a_02_contract():
    diagnosis = equipment_agent.diagnose_equipment("CNC02")

    assert DIAGNOSIS_KEYS <= set(diagnosis), "诊断输出缺少 S3-A-02 约定字段"
    assert diagnosis["equipment"] == "CNC02"
    assert diagnosis["status"] == "abnormal"
    assert diagnosis["fault"]
    assert 0 < diagnosis["confidence"] <= 1
    assert diagnosis["recommendation"]
    assert diagnosis["possible_causes"]
    assert diagnosis["risk"] in {"low", "medium", "high"}
    assert diagnosis["knowledge_base_size"] >= 20

    json.dumps(diagnosis, ensure_ascii=False)


def test_diagnose_healthy_equipment_reports_normal():
    diagnosis = equipment_agent.diagnose_equipment("CNC01")

    assert diagnosis["status"] == "normal"
    assert diagnosis["fault"] is None
    assert diagnosis["confidence"] == 0.0
    assert diagnosis["recommendation"] == ["设备运行参数正常，保持常规点检"]
    assert diagnosis["risk"] == "low"


def test_diagnose_unknown_equipment_is_graceful():
    diagnosis = equipment_agent.diagnose_equipment("XXX99")

    assert diagnosis["status"] == "unknown"
    assert diagnosis["fault"] is None
    assert diagnosis["recommendation"]
    assert diagnosis["risk"] == "medium"


def test_diagnose_from_alarm_text_only():
    """只有现场报警文本与温度时也能诊断（不依赖台账与传感器历史）。"""
    diagnosis = equipment_agent.diagnose_equipment(
        "XXX99",
        observation={"text": "主轴过热报警", "温度": 95, "alarm": True, "equipment_type": "CNC"},
    )

    assert diagnosis["status"] == "abnormal"
    assert diagnosis["fault"] == "主轴温升异常"
    assert "检查润滑系统" in diagnosis["recommendation"]
    assert diagnosis["possible_causes"]


def test_diagnose_generates_work_order_draft_without_persisting(tmp_path):
    target = tmp_path / "work_orders.csv"

    diagnosis = equipment_agent.diagnose_equipment("WELD02", work_order_path=target)

    assert diagnosis["status"] == "abnormal"
    assert diagnosis["work_order"] is not None
    assert diagnosis["work_order"]["设备"] == "WELD02"
    assert diagnosis["work_order"]["优先级"] == "紧急"
    assert not target.exists(), "默认只生成工单草稿，不落库"


# --------------------------------------------------------------------------
# S3-A-03 维修工单工具
# --------------------------------------------------------------------------


def test_create_work_order_generates_required_fields(tmp_path):
    target = tmp_path / "work_orders.csv"

    record = work_order_tools.create_work_order(
        "CNC02",
        "轴承磨损",
        equipment_status="warning",
        equipment_type="CNC",
        confidence=0.95,
        evidence="振动>3.5mm/s 命中（实测 6.2）",
        created_at="2026-10-11T09:00:00",
        path=target,
    )

    for field in WORK_ORDER_REQUIRED_FIELDS:
        assert record[field], f"缺少工单字段：{field}"

    assert record["维修编号"] == "WO-20261011-001"
    assert record["设备"] == "CNC02"
    assert record["故障"] == "轴承磨损"
    assert record["优先级"] == "高"
    assert record["负责人"] == "机加维修组"
    assert pd.Timestamp(record["建议时间"]) == pd.Timestamp("2026-10-12T09:00:00")
    assert record["状态"] == "待处理"
    assert target.is_file()


def test_create_work_order_number_sequence_and_query(tmp_path):
    target = tmp_path / "work_orders.csv"

    first = work_order_tools.create_work_order(
        "CNC02", "故障A", created_at="2026-10-11T09:00:00", path=target
    )
    second = work_order_tools.create_work_order(
        "CNC02", "故障B", created_at="2026-10-11T10:00:00", path=target
    )
    third = work_order_tools.create_work_order(
        "WELD02", "故障C", created_at="2026-10-11T11:00:00", path=target
    )
    next_day = work_order_tools.create_work_order(
        "CNC01", "故障D", created_at="2026-10-12T09:00:00", path=target
    )

    assert [first["维修编号"], second["维修编号"], third["维修编号"]] == [
        "WO-20261011-001",
        "WO-20261011-002",
        "WO-20261011-003",
    ]
    assert next_day["维修编号"] == "WO-20261012-001"

    assert len(work_order_tools.query_work_orders(path=target)) == 4
    filtered = work_order_tools.query_work_orders(equipment="CNC02", path=target)
    assert list(filtered["设备"]) == ["CNC02", "CNC02"]


def test_create_work_order_priority_and_owner_rules(tmp_path):
    target = tmp_path / "work_orders.csv"

    urgent = work_order_tools.create_work_order(
        "WELD02", "停机", equipment_status="fault", equipment_type="WELDING",
        created_at="2026-10-11T09:00:00", path=target,
    )
    high = work_order_tools.create_work_order(
        "CNC02", "预警", equipment_status="warning", created_at="2026-10-11T09:00:00", path=target
    )
    normal = work_order_tools.create_work_order(
        "TEST01", "常规点检", equipment_status="normal", equipment_type="TESTING",
        created_at="2026-10-11T09:00:00", path=target,
    )
    explicit = work_order_tools.create_work_order(
        "CNC01", "指定优先级", priority="普通", created_at="2026-10-11T09:00:00", path=target
    )

    assert [urgent["优先级"], high["优先级"], normal["优先级"], explicit["优先级"]] == [
        "紧急",
        "高",
        "普通",
        "普通",
    ]
    assert urgent["负责人"] == "焊接维修组"
    assert normal["负责人"] == "检测维修组"
    # 未提供设备类型时回落到默认维修组
    assert high["负责人"] == "设备维修组"
    assert explicit["负责人"] == "设备维修组"


def test_create_work_order_can_skip_persistence(tmp_path):
    target = tmp_path / "work_orders.csv"

    record = work_order_tools.create_work_order(
        "CNC02", "轴承磨损", persist=False, created_at="2026-10-11T09:00:00", path=target
    )

    assert record["维修编号"].startswith("WO-")
    assert not target.exists()


def test_seeded_work_order_file_has_documented_columns():
    frame = work_order_tools.load_work_orders()

    assert list(frame.columns) == work_order_tools.WORK_ORDER_COLUMNS
    assert len(frame) >= 2


# --------------------------------------------------------------------------
# S3-A-04 Supervisor 接入
# --------------------------------------------------------------------------


def test_supervisor_routes_equipment_alarm_to_equipment_agent():
    plan = supervisor_agent.build_plan("CNC02报警了，帮我分析")

    assert plan["intent_code"] == "equipment_failure"
    assert plan["capabilities"] == ["equipment_failure"]
    assert plan["entities"]["equipment_id"] == "CNC02"
    assert plan["entities"]["order_ids"] == []

    step = plan["steps"][0]
    assert step["agent"] == "equipment_agent"
    assert step["action"] == "diagnose_equipment_failure"
    assert step["arguments"] == {"equipment_id": "CNC02"}


def test_supervisor_equipment_failure_execution_and_risk_section():
    outcome = supervisor_agent.handle("CNC02报警了，帮我分析")

    assert set(outcome["results"]) == {"equipment_agent"}
    result = outcome["results"]["equipment_agent"]
    assert result["status"] == "ok"
    assert result["device_status"] == "abnormal"
    assert result["fault"]
    assert DIAGNOSIS_KEYS <= set(result["diagnosis"])
    assert result["diagnosis"]["equipment"] == "CNC02"

    sections = outcome["risk_report"]["sections"]
    assert [section["title"] for section in sections] == ["设备故障风险"]
    assert sections[0]["risk"] in {"medium", "high"}

    json.dumps(outcome, ensure_ascii=False)


def test_supervisor_equipment_failure_requires_equipment_entity():
    """未指向具体设备时不误触发设备故障诊断。"""
    plan = supervisor_agent.build_plan("设备有没有故障，顺便看下质量缺陷")

    assert plan["intent_code"] == "mixed_query"
    assert set(plan["capabilities"]) == {"equipment", "quality"}


def test_equipment_id_is_not_mistaken_for_order_id():
    """回归：CNC02 这类设备编号不能被当成订单编号。"""
    known_orders = supervisor_agent._known_order_ids()
    known_equipment = supervisor_agent._known_equipment_ids()

    assert supervisor_agent.extract_order_ids("CNC02报警了", known_orders) == []
    assert supervisor_agent.extract_equipment_ids("CNC02报警了", known_equipment) == ["CNC02"]

    entities = supervisor_agent.extract_entities("CNC02报警了，帮我分析")
    assert entities["order_id"] is None
    assert entities["equipment_id"] == "CNC02"

    assert supervisor_agent.extract_entities("分析订单O001能否按时完成")["order_id"] == "O001"


def test_equipment_agent_run_handles_missing_equipment_id():
    result = equipment_agent.run(capabilities=["equipment_failure"], arguments={})

    assert result["status"] == "ok"
    assert result["fault"] is None
    assert "未提供设备编号" in result["reason"]


def test_equipment_fleet_capability_is_unchanged():
    result = equipment_agent.run(capabilities=["equipment"])

    assert result["status"] == "ok"
    assert result["risk"] == "high"
    assert result["equipment_summary"]["fault_count"] == 1
    assert result["sensor_summary"]["alarm_count"] > 0


def test_equipment_knowledge_wrapper_exposes_case_count():
    assert equipment_tools.get_fault_knowledge_count() >= 20
    matches = equipment_tools.search_fault_knowledge({"温度": 95, "equipment_status": "fault"}, limit=2)
    assert matches
    assert matches[0]["标题"] == "主轴温升异常"


def test_s3_reference_date_is_stable():
    """S3 用例统一使用 2026-10-11 作为参考日期，避免时间漂移。"""
    assert date(2026, 10, 11).isoformat() == "2026-10-11"
