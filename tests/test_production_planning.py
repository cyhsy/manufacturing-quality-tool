"""S5-A 测试：排产规则引擎 / 生产计划工具 / Planning Agent / Supervisor 接入。

覆盖：
- S5-A-03 规则模型：交期优先、避开故障设备、高优先级加急、库存缺口；
- S5-A-02 生产计划工具：订单数量/交期/产能/故障设备/库存风险，以及数据来源；
- S5-A-01 Planning Agent：调用 order_agent / inventory_tool / production_tool / equipment_agent；
- S5-A-04 Supervisor：production_planning 能力与既有路由不被破坏。
"""

import json
from pathlib import Path

import pytest

from agent_tools import order_tools, planning_tools
from agents import order_agent, planning_agent, supervisor_agent
from modules import planning_engine
from modules.planning_engine import evaluate_effective_capacity
from tools.production_tool import query_production_capacity


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TODAY = "2026-10-11"

# Sprint 5 验收输入
ACCEPTANCE = "这个订单怎么安排生产？"


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY，避免规划类测试意外发起真实 LLM 调用。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def _scenario_plan():
    """Sprint 5 场景：10000 件电机壳体，15 天交付。"""
    return planning_tools.generate_production_plan(
        product="电机壳体", quantity=10000, delivery_days=15, today=TODAY
    )


# --------------------------------------------------------------------------
# S5-A-03 排产规则模型
# --------------------------------------------------------------------------


def test_capacity_model_is_shared_with_order_agent():
    """「有效日产能」只有一份实现：order_agent 与排产引擎结果一致。"""
    lines = order_tools.get_production_lines(product="电机壳体")
    statuses = planning_tools.get_equipment_status_map()

    from_engine = evaluate_effective_capacity(lines, statuses)
    from_order_agent = order_agent.evaluate_capacity("电机壳体")

    assert from_engine == from_order_agent
    assert from_engine["bottleneck"] == 800


def test_rule_one_deadline_drives_timeline():
    plan = _scenario_plan()
    timeline = plan["timeline"]

    assert timeline["available_days"] == 15
    assert timeline["material_days"] == 3
    assert timeline["production_days"] == 14
    assert timeline["total_days"] == 17
    assert timeline["serial_days"] == 35
    assert timeline["feasible"] is False
    assert timeline["gap_days"] == 2
    assert plan["status"] == "tight"


def test_rule_two_avoids_faulty_equipment_by_substitution():
    """O002 的 CNC02 停机 -> 计划自动改用 CNC03。"""
    plan = planning_tools.generate_production_plan(order_id="O002", today=TODAY)

    stages = {stage["process"]: stage for stage in plan["capacity"]["stages"]}
    cnc = stages["CNC加工"]
    assert cnc["original_equipment"] == "CNC02"
    assert cnc["substituted"] is True
    assert cnc["equipment"] == "CNC03"
    assert cnc["effective_capacity"] == 850
    assert plan["status"] == "ok"

    risk = next(item for item in plan["risks"] if "原设备 CNC02" in item["item"])
    assert risk["level"] == "medium"
    assert "改用替代设备 CNC03" in risk["impact"]

    schedule = {item["activity"]: item for item in plan["schedule"] if item["type"] == "process"}
    assert schedule["CNC加工"]["equipment"] == "CNC03"


def test_rule_two_reports_unavailable_alternatives():
    """Sprint 5 场景：电机壳体的 CNC加工 备用设备 CNC02 停机需被提示。"""
    plan = _scenario_plan()

    risks = plan["risks"]
    assert any("备用设备 CNC02 停机或故障" in item["item"] for item in risks)
    assert any(item["impact"] == "扩产时不可用（日产能 600 件）" for item in risks)

    suggestion = next(item for item in plan["suggestions"] if "替代/并行设备" in item)
    assert suggestion.count("CNC03") == 1  # 同一设备去重
    assert "瓶颈产能 800 → 1650 件/天" in suggestion


def test_rule_three_high_priority_uses_express_purchase():
    """O009 优先级 high -> 采购按加急 1 天处理。"""
    plan = planning_tools.generate_production_plan(order_id="O009", today=TODAY)

    assert plan["priority"] == "high"
    assert plan["material"]["express"] is True
    assert plan["material"]["purchase_days"] == planning_engine.PURCHASE_LEAD_DAYS_EXPRESS
    assert plan["schedule"][0]["days"] == planning_engine.PURCHASE_LEAD_DAYS_EXPRESS


def test_rule_four_material_shortage_inserts_purchase_phase():
    plan = _scenario_plan()

    assert plan["material"]["shortage_materials"] == ["铝合金"]
    requirement = plan["material"]["requirements"][0]
    assert requirement["material"] == "铝合金"
    assert requirement["required"] == 25000  # 2.5 kg/件 × 10000
    assert requirement["stock"] == 5000
    assert requirement["shortage"] == 20000
    assert requirement["below_safety_after"] is True

    assert plan["schedule"][0]["type"] == "material"
    assert "采购备料" in plan["schedule"][0]["activity"]
    assert plan["timeline"]["material_days"] == 3


def test_no_shortage_skips_purchase_phase():
    plan = planning_tools.generate_production_plan(
        product="传感器外壳", quantity=100, delivery_days=30, today=TODAY
    )

    requirement = plan["material"]["requirements"][0]
    assert requirement["required"] == 40
    assert requirement["shortage"] == 0
    assert plan["timeline"]["material_days"] == 0
    assert plan["schedule"][0]["type"] == "process"


def test_plan_lines_are_human_readable_day_ranges():
    lines = _scenario_plan()["plan_lines"]

    assert lines[0].startswith("Day1-3：采购备料（铝合金）")
    assert any(line.startswith("Day4-13：铸造（CAST01，1000 件/天，需 10 天）") for line in lines)
    assert any(line.startswith("Day5-17：CNC加工（CNC01，800 件/天，需 13 天）") for line in lines)
    assert any(line.startswith("Day7-11：检测（TEST01，2000 件/天，需 5 天）") for line in lines)


def test_blocked_stage_without_alternative_is_reported_as_blocked():
    plan = planning_engine.build_production_plan(
        product="测试件",
        quantity=100,
        deadline="2026-11-01",
        today=TODAY,
        capacity={
            "source": "product_process_bottleneck",
            "bottleneck": 0,
            "lines": [
                {
                    "process": "焊接",
                    "equipment": "WELD02",
                    "status": "stopped",
                    "equipment_status": "fault",
                    "daily_capacity": 0,
                    "effective_capacity": 0,
                    "blocked": True,
                    "derated": False,
                }
            ],
            "blocked_lines": [],
            "derated_lines": [],
        },
        alternatives={
            "焊接": [{"equipment": "WELD02", "daily_capacity": 0, "blocked": True, "status": "stopped"}]
        },
        material_requirements=[],
    )

    assert plan["status"] == "blocked"
    assert plan["timeline"]["production_days"] is None
    assert any(
        item["level"] == "high" and "无可用替代设备" in item["impact"] for item in plan["risks"]
    )


def test_product_without_process_lines_is_reported():
    plan = planning_engine.build_production_plan(
        product="未知产品",
        quantity=100,
        deadline="2026-11-01",
        today=TODAY,
        capacity={
            "source": "factory_running_capacity",
            "bottleneck": None,
            "lines": [],
            "blocked_lines": [],
            "derated_lines": [],
        },
        alternatives={},
        material_requirements=[],
    )

    assert plan["status"] == "blocked"
    assert any("没有对应产线" in item["item"] for item in plan["risks"])
    assert plan["suggestions"]


# --------------------------------------------------------------------------
# S5-A-02 生产计划工具
# --------------------------------------------------------------------------


def test_tool_requires_product_and_quantity():
    result = planning_tools.generate_production_plan()

    assert result["status"] == "error"
    assert "缺少产品与数量" in result["reason"]
    assert result["suggestion"]


def test_tool_reports_data_sources_and_order_context():
    plan = planning_tools.generate_production_plan(order_id="O001", today=TODAY)

    for key in ("order", "production", "equipment", "inventory", "bom", "engine"):
        assert plan["sources"][key], key
    assert plan["order_source"] == "erp_order"
    assert plan["order_id"] == "O001"
    assert plan["priority"] == "high"


def test_bom_covers_every_product_in_production():
    covered = set(planning_tools.list_bom_products())
    products = set(query_production_capacity()["product"])

    assert products <= covered


# --------------------------------------------------------------------------
# S5-A-01 Planning Agent
# --------------------------------------------------------------------------


def test_planning_agent_aggregates_all_required_sources():
    result = planning_agent.build_plan(
        product="电机壳体", quantity=10000, delivery_days=15, today=TODAY
    )

    assert result["agent"] == "planning_agent"
    assert result["sources"]["order"].startswith("agent_tools.order_tools")

    # agents.order_agent
    assert result["delivery_baseline"]["risk"] in {"low", "medium", "high"}
    # agent_tools.inventory_tools
    assert result["inventory_risk"]["material_count"] == 13
    assert result["inventory_risk"]["shortage_count"] == 4
    # agents.equipment_agent
    assert result["equipment_risk"]["risk"] == "high"
    assert result["equipment_risk"]["abnormal_count"] == 5
    # agents.quality_agent
    assert result["quality_risk"]["risk"] in {"low", "medium", "high"}
    assert result["quality_risk"]["total_defects"] == 820

    assert result["risk"] == "high"
    assert result["plan_status"] == "tight"
    assert "超出 2 天" in result["reason"]
    assert result["plan_lines"] and result["suggestions"]


def test_planning_agent_defaults_to_most_urgent_order():
    result = planning_agent.build_plan(today=TODAY)

    assert result["request"]["order_id"] == "O001"
    assert result["assumptions"] and "最紧急" in result["assumptions"][0]
    assert len(result["candidate_order_ids"]) == 15


def test_planning_agent_handles_missing_quantity():
    result = planning_agent.run(
        capabilities=["production_planning"], arguments={"product": "电机壳体"}
    )

    assert result["risk"] == "unknown"
    assert "缺少产品与数量" in result["reason"]


def test_planning_agent_can_skip_quality_agent():
    result = planning_agent.build_plan(
        order_id="O001", today=TODAY, include_quality=False, include_equipment=False
    )

    assert result["quality_risk"] is None
    assert result["equipment_risk"] is None
    assert result["plan_lines"]


# --------------------------------------------------------------------------
# S5-A-04 Supervisor 接入
# --------------------------------------------------------------------------


def test_supervisor_routes_planning_question():
    plan = supervisor_agent.build_plan(ACCEPTANCE)

    assert plan["intent_code"] == "production_planning"
    assert plan["capabilities"] == ["production_planning"]

    step = plan["steps"][0]
    assert step["agent"] == "planning_agent"
    assert step["action"] == "generate_production_plan"


def test_supervisor_planning_takes_precedence_over_delivery_check():
    """「怎么安排生产」比「能否按时完成」更具体，应路由到排产。"""
    plan = supervisor_agent.build_plan("10000件电机壳体，15天交付，怎么安排生产")

    assert plan["intent_code"] == "production_planning"
    assert plan["entities"]["product"] == "电机壳体"
    assert plan["entities"]["quantity"] == 10000
    assert plan["entities"]["delivery_days"] == 15
    assert plan["steps"][0]["arguments"] == {
        "product": "电机壳体",
        "quantity": 10000,
        "delivery_days": 15,
    }


def test_supervisor_planning_with_order_id_and_existing_routes_intact():
    plan = supervisor_agent.build_plan("O009怎么排产")
    assert plan["intent_code"] == "production_planning"
    assert plan["steps"][0]["arguments"] == {"order_id": "O009"}

    # 回归：交付判定、设备故障、质量议题、质量总览路由保持不变
    assert (
        supervisor_agent.build_plan("分析订单O001能否按时完成")["intent_code"]
        == "order_delivery"
    )
    assert (
        supervisor_agent.build_plan("CNC02报警了，帮我分析")["intent_code"]
        == "equipment_failure"
    )
    assert (
        supervisor_agent.build_plan("最近电机壳体良率下降，分析原因")["intent_code"]
        == "quality_issue_analysis"
    )
    assert supervisor_agent.build_plan("看看质量缺陷情况")["intent_code"] == "quality_query"


def test_supervisor_end_to_end_planning():
    outcome = supervisor_agent.handle(ACCEPTANCE)

    assert set(outcome["results"]) == {"planning_agent"}
    result = outcome["results"]["planning_agent"]
    assert result["capabilities"] == ["production_planning"]
    assert result["request"]["order_id"] == "O001"
    assert result["plan_lines"]
    assert result["suggestions"]

    sections = outcome["risk_report"]["sections"]
    assert [section["title"] for section in sections] == ["生产计划风险"]
    assert sections[0]["risk"] in {"low", "medium", "high"}

    json.dumps(outcome, ensure_ascii=False)


def test_sprint5_outputs_are_json_serializable():
    payloads = {
        "tool": planning_tools.generate_production_plan(order_id="O002", today=TODAY),
        "agent": planning_agent.build_plan(
            product="电机壳体", quantity=10000, delivery_days=15, today=TODAY
        ),
        "supervisor": supervisor_agent.handle(ACCEPTANCE),
    }

    for name, payload in payloads.items():
        assert json.dumps(payload, ensure_ascii=False), name
