"""Agent 层测试（S2-A-02 ~ S2-A-05）。

覆盖：
- 分层约束：agent_tools 不复制 tools，Agent 不直接读 CSV；
- Supervisor Agent：意图识别、依赖扩张、执行计划、调度与 LLM 回退；
- Order Agent：订单可交付分析的结构化输出与风险判定；
- Equipment Agent / Quality Agent：设备与质量分析，质量系统为包装而非重写；
- 所有 Agent 输出均可 JSON 序列化。
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd

from agent_tools import df_to_records
from agents import equipment_agent, order_agent, quality_agent, supervisor_agent
from modules.quality_analysis import analyze_quality_overview


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 11)


# --------------------------------------------------------------------------
# S2-A-02：分层约束（agent_tools / agents 都不得复制 tools 的取数逻辑）
# --------------------------------------------------------------------------


def test_agent_tools_do_not_read_csv_directly():
    modules = [
        path
        for path in sorted((PROJECT_ROOT / "agent_tools").glob("*.py"))
        if path.name != "__init__.py"
    ]
    assert modules, "agent_tools 下没有模块"

    for path in modules:
        source = path.read_text(encoding="utf-8")
        assert "read_csv" not in source, f"{path.name} 直接读 CSV，违反分层"
        assert "from tools" in source or "from modules" in source, (
            f"{path.name} 未通过 tools/ 或 modules/ 层取数"
        )


def test_agents_do_not_read_csv_directly():
    modules = [
        path
        for path in sorted((PROJECT_ROOT / "agents").glob("*.py"))
        if path.name != "__init__.py"
    ]
    assert modules, "agents 下没有模块"

    for path in modules:
        source = path.read_text(encoding="utf-8")
        assert "read_csv" not in source, f"{path.name} 直接读 CSV，违反分层"
        assert "agent_tools" in source, f"{path.name} 未经过 agent_tools 层"


def test_agent_tools_delegate_to_tools_layer():
    """agent_tools 的取数结果必须与 tools 层一致。"""
    from agent_tools import order_tools
    from tools.order_tool import query_orders

    assert len(order_tools.get_orders()) == len(query_orders())
    assert order_tools.get_order("O001")["product"] == "电机壳体"
    assert order_tools.get_order("O999") is None
    assert "O001" in order_tools.list_order_ids()


# --------------------------------------------------------------------------
# JSON 友好化工具
# --------------------------------------------------------------------------


def test_to_jsonable_handles_pandas_types():
    records = df_to_records(
        pd.DataFrame(
            {
                "when": [pd.Timestamp("2026-10-11")],
                "ratio": [float("nan")],
                "count": [7],
            }
        )
    )
    assert records == [{"when": "2026-10-11T00:00:00", "ratio": None, "count": 7}]
    assert json.dumps(records)


# --------------------------------------------------------------------------
# S2-A-03：Supervisor Agent
# --------------------------------------------------------------------------


def test_supervisor_plan_for_order_delivery_question():
    """任务书示例：分析订单O001能否按时完成 -> 订单 + 库存 + 生产。"""
    plan = supervisor_agent.build_plan("分析订单O001能否按时完成")

    assert plan["intent_code"] == "order_delivery"
    assert plan["intent"] == "订单交付能力分析"
    assert plan["capabilities"] == ["order", "inventory", "production"]
    assert plan["entities"]["order_id"] == "O001"
    assert plan["entities"]["order_ids"] == ["O001"]
    assert plan["planner"] == "rule"

    assert [step["step"] for step in plan["steps"]] == [1, 2, 3]
    assert [step["capability"] for step in plan["steps"]] == ["order", "inventory", "production"]
    assert [step["agent"] for step in plan["steps"]] == ["order_agent"] * 3
    assert plan["steps"][0]["action"] == "analyze_order_delivery"
    assert all(step["reason"] for step in plan["steps"])


def test_supervisor_routes_equipment_and_quality_to_their_agents():
    plan = supervisor_agent.build_plan("设备有没有故障，顺便看下质量缺陷")

    assert plan["intent_code"] == "mixed_query"
    assert {step["agent"] for step in plan["steps"]} == {
        "equipment_agent",
        "quality_agent",
    }
    assert {step["capability"] for step in plan["steps"]} == {"equipment", "quality"}


def test_supervisor_single_capability_intents():
    assert supervisor_agent.build_plan("看看质量缺陷情况")["intent_code"] == "quality_query"
    assert supervisor_agent.build_plan("设备维保情况")["intent_code"] == "equipment_query"
    assert supervisor_agent.build_plan("库存够吗")["intent_code"] == "inventory_query"

    overview_plan = supervisor_agent.build_plan("今天工厂什么情况")
    assert overview_plan["intent_code"] == "overview"
    assert overview_plan["capabilities"] == [
        "order",
        "inventory",
        "production",
        "equipment",
        "quality",
    ]


def test_supervisor_extracts_only_known_order_ids():
    assert supervisor_agent.extract_order_ids("分析订单O001和X999", known_order_ids=["O001", "O002"]) == [
        "O001"
    ]
    assert supervisor_agent.extract_order_ids("订单O001", known_order_ids=["O001"]) == ["O001"]


def test_supervisor_llm_disabled_falls_back_to_rules(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    plan = supervisor_agent.build_plan("分析订单O001能否按时完成", use_llm=True)

    assert plan["planner"] == "rule"
    assert any("回退规则规划" in note for note in plan["notes"])
    assert plan["capabilities"] == ["order", "inventory", "production"]


def test_supervisor_executes_plan_and_returns_structured_results():
    outcome = supervisor_agent.handle("分析订单O001能否按时完成")

    assert outcome["plan"]["intent_code"] == "order_delivery"
    assert set(outcome["results"]) == {"order_agent"}

    order_result = outcome["results"]["order_agent"]
    assert order_result["status"] == "ok"
    assert order_result["risk"] in {"low", "medium", "high"}
    assert order_result["capabilities"] == ["order", "inventory", "production"]
    assert order_result["deliverability"]["order_id"] == "O001"

    json.dumps(outcome, ensure_ascii=False)  # 必须可 JSON 序列化


def test_supervisor_isolates_agent_failure(monkeypatch):
    """单个 Agent 失败时只记录该 Agent 的 error，不影响整体计划。"""

    def broken_runner(capabilities=None, arguments=None):
        raise RuntimeError("模拟 Agent 故障")

    monkeypatch.setitem(supervisor_agent.AGENT_DISPATCH, "order_agent", broken_runner)

    plan = supervisor_agent.build_plan("分析订单O001能否按时完成")
    execution = supervisor_agent.execute_plan(plan)

    assert execution["results"]["order_agent"]["status"] == "error"
    assert "模拟 Agent 故障" in execution["results"]["order_agent"]["reason"]


def test_supervisor_explain_plan_is_human_readable():
    plan = supervisor_agent.build_plan("分析订单O001能否按时完成")
    text = supervisor_agent.explain_plan(plan)

    assert "订单交付能力分析" in text
    assert "order_agent" in text
    assert "库存" in text and "生产" in text


# --------------------------------------------------------------------------
# S2-A-04：Order Agent
# --------------------------------------------------------------------------


def test_order_agent_returns_structured_deliverability_output():
    analysis = order_agent.analyze_order_delivery("O001", today=TODAY)

    for key in ("risk", "reason", "suggestion"):
        assert key in analysis, f"缺少结构化字段：{key}"
    assert analysis["risk"] == "low"
    assert analysis["order_id"] == "O001"
    assert analysis["product"] == "电机壳体"
    assert analysis["quantity"] == 10000
    assert analysis["bottleneck_daily_capacity"] == 800
    assert analysis["required_days"] == 13
    assert analysis["available_days"] == 21
    assert "产能可满足" in analysis["reason"]
    assert analysis["material_summary"]["shortage_count"] == 4


def test_order_agent_flags_blocked_process_as_high_risk():
    """电池托盘依赖停机产线 WELD02 -> 高风险。"""
    analysis = order_agent.analyze_order_delivery("O009", today=TODAY)

    assert analysis["risk"] == "high"
    assert "关键工序不可用" in analysis["reason"]
    blocked = analysis["capacity_lines"]
    assert any(line["blocked"] for line in blocked)
    assert analysis["required_days"] is None


def test_order_agent_flags_stopped_equipment_on_serial_process():
    """变速箱壳体的 CNC 工序设备停机 -> 高风险。"""
    analysis = order_agent.analyze_order_delivery("O002", today=TODAY)

    assert analysis["risk"] == "high"
    assert any(
        line["blocked"] and line["equipment"] == "CNC02"
        for line in analysis["capacity_lines"]
    )


def test_order_agent_falls_back_to_factory_capacity_when_no_lines():
    """电机端盖在 MES 中没有产线 -> 回退全厂在产产能并给出说明。"""
    analysis = order_agent.analyze_order_delivery("O003", today=TODAY)

    assert analysis["capacity_source"] == "factory_running_capacity"
    assert analysis["bottleneck_daily_capacity"] == 14300
    assert any("回退" in note for note in analysis["notes"])


def test_order_agent_handles_unknown_order():
    analysis = order_agent.analyze_order_delivery("O999", today=TODAY)

    assert analysis["risk"] == "unknown"
    assert "未找到订单 O999" in analysis["reason"]
    assert any("O001" in note for note in analysis["notes"])


def test_order_agent_run_without_order_id_returns_overview():
    result = order_agent.run(capabilities=["order", "inventory", "production"])

    assert result["agent"] == "order_agent"
    assert result["risk"] in {"low", "medium"}
    assert result["order_summary"]["order_count"] == 15
    assert result["capacity_summary"]["running_daily_capacity"] == 14300
    assert result["material_summary"]["shortage_count"] == 4


# --------------------------------------------------------------------------
# Equipment / Quality Agent
# --------------------------------------------------------------------------


def test_equipment_agent_reports_fault_as_high_risk():
    result = equipment_agent.run(capabilities=["equipment"], arguments={"today": TODAY})

    assert result["status"] == "ok"
    assert result["risk"] == "high"
    assert result["equipment_summary"]["fault_count"] == 1
    assert "WELD02" in result["reason"]
    assert result["sensor_summary"]["alarm_count"] > 0
    assert result["maintenance_due"]


def test_quality_agent_wraps_existing_quality_system():
    """质量 Agent 必须复用原有分析结果，而不是另一套统计口径。"""
    original = analyze_quality_overview()
    result = quality_agent.run(capabilities=["quality"])

    assert result["status"] == "ok"
    assert result["risk"] in {"low", "medium", "high"}
    assert result["metrics"]["total_defects"] == original["total_defect_count"]
    assert result["metrics"]["defect_type_count"] == original["defect_type_count"]
    assert result["metrics"]["top_defect_type"] == original["top_defect_type"]
    assert result["summary_lines"] == original["summary_lines"]
    assert "modules/quality_analysis" in result["data_source"]


def test_quality_agent_can_lookup_root_causes():
    result = quality_agent.run(
        capabilities=["quality"],
        arguments={"defect_type": "气孔", "process": "铸造"},
    )

    assert result["root_cause_lookup"]["defect_type"] == "气孔"
    assert result["root_cause_lookup"]["causes"]


def test_all_agent_outputs_are_json_serializable():
    payloads = {
        "order": order_agent.run(
            capabilities=["order", "inventory", "production"],
            arguments={"order_id": "O001"},
        ),
        "equipment": equipment_agent.run(),
        "quality": quality_agent.run(),
        "supervisor": supervisor_agent.handle("分析订单O001能否按时完成"),
    }

    for name, payload in payloads.items():
        text = json.dumps(payload, ensure_ascii=False)
        assert text, f"{name} 输出无法序列化"
