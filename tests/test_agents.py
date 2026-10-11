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
from types import SimpleNamespace

import pandas as pd
import pytest

from agent_tools import df_to_records
from agents import equipment_agent, order_agent, quality_agent, supervisor_agent
from modules.quality_analysis import analyze_quality_overview


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 11)

# 审查验收输入：口述订单 + 风险问答（无订单编号）
ACCEPTANCE_INPUT = "工厂收到10000件电机壳体订单，15天交付，帮我分析风险"


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY：避免规则类测试意外发起真实 LLM 调用。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def _fake_llm_factory(payload_text):
    """构造返回固定内容的假 LLM 客户端工厂（用于测试 LLM 规划路径）。"""

    def factory(timeout=20):
        def create(**_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=payload_text))]
            )

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

    return factory


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


# --------------------------------------------------------------------------
# S2 审查修复：实体抽取（口述订单）
# --------------------------------------------------------------------------


def test_entity_extraction_from_natural_language():
    entities = supervisor_agent.extract_entities(
        "工厂收到10000件电机壳体订单，15天交付，帮我分析风险"
    )
    assert entities["product"] == "电机壳体"
    assert entities["quantity"] == 10000
    assert entities["delivery_days"] == 15
    assert entities["order_id"] is None

    weekly = supervisor_agent.extract_entities("2000件涡轮支架，2周内交付")
    assert weekly["product"] == "涡轮支架"
    assert weekly["quantity"] == 2000
    assert weekly["delivery_days"] == 14

    dated = supervisor_agent.extract_entities("订单O002 于 2026-11-10 交付")
    assert dated["order_id"] == "O002"
    assert dated["deadline"] == "2026-11-10"


def test_order_agent_analyzes_order_described_in_text():
    """口述订单（无订单编号）同样要回答「这一单有没有风险」。"""
    analysis = order_agent.analyze_order_request(
        product="电机壳体", quantity=10000, delivery_days=15, today=TODAY
    )

    assert analysis["risk"] == "medium"
    assert analysis["order_source"] == "user_description"
    assert analysis["order_id"] is None
    assert analysis["product"] == "电机壳体"
    assert analysis["quantity"] == 10000
    assert analysis["available_days"] == 15
    assert analysis["required_days"] == 13
    assert analysis["delivery_days"] == 15
    assert "交期较紧" in analysis["reason"]
    assert [item["order_id"] for item in analysis["matched_orders"]] == ["O001"]


def test_order_agent_text_order_with_short_horizon_is_high():
    analysis = order_agent.analyze_order_request(
        product="电机壳体", quantity=10000, delivery_days=7, today=TODAY
    )

    assert analysis["risk"] == "high"
    assert analysis["available_days"] == 7
    assert "产能不足" in analysis["reason"]


def test_order_agent_text_order_without_product_or_quantity():
    analysis = order_agent.analyze_order_request(product=None, quantity=None)

    assert analysis["risk"] == "unknown"
    assert "缺少产品名称或数量" in analysis["reason"]


# --------------------------------------------------------------------------
# S2 审查修复：风险类问题覆盖五维能力
# --------------------------------------------------------------------------


def test_risk_query_expands_to_all_five_capabilities():
    plan = supervisor_agent.build_plan(ACCEPTANCE_INPUT)

    assert plan["intent_code"] == "comprehensive_risk"
    assert plan["risk_focus"] is True
    assert plan["capabilities"] == [
        "order",
        "inventory",
        "production",
        "equipment",
        "quality",
    ]
    assert plan["entities"]["product"] == "电机壳体"
    assert plan["entities"]["quantity"] == 10000
    assert plan["entities"]["delivery_days"] == 15

    actions = {step["capability"]: step["action"] for step in plan["steps"]}
    assert actions["order"] == "analyze_order_request"
    assert actions["equipment"] == "analyze_equipment_status"
    assert actions["quality"] == "analyze_quality"
    assert {step["agent"] for step in plan["steps"]} == {
        "order_agent",
        "equipment_agent",
        "quality_agent",
    }


def test_risk_query_invokes_quality_and_equipment_agents():
    outcome = supervisor_agent.handle(ACCEPTANCE_INPUT)

    assert set(outcome["results"]) == {
        "order_agent",
        "equipment_agent",
        "quality_agent",
    }
    for agent_name in ("order_agent", "equipment_agent", "quality_agent"):
        assert outcome["results"][agent_name]["status"] == "ok", agent_name


def test_risk_report_contains_quality_and_equipment_sections():
    outcome = supervisor_agent.handle(ACCEPTANCE_INPUT)
    report = outcome["risk_report"]

    titles = [section["title"] for section in report["sections"]]
    for expected in [
        "订单交付风险",
        "物料库存风险",
        "产能风险",
        "设备风险",
        "质量风险",
    ]:
        assert expected in titles, f"风险报告缺少分段：{expected}"

    assert report["overall_risk"] in {"low", "medium", "high"}
    for section in report["sections"]:
        assert section["risk"] in {"low", "medium", "high", "unknown"}
        assert section["reason"]

    json.dumps(outcome, ensure_ascii=False)


def test_risk_report_order_section_answers_the_described_order():
    outcome = supervisor_agent.handle(ACCEPTANCE_INPUT)

    section = next(
        item for item in outcome["risk_report"]["sections"] if item["capability"] == "order"
    )

    # 交期天数由用户给出（相对今天），因此结果稳定可复现：需 13 天 ≤ 15 天但 > 0.8×15 → medium
    assert section["risk"] == "medium"
    assert section["order_source"] == "user_description"
    assert section["order_id"] is None


def test_taskbook_example_keeps_three_capability_scope():
    """任务书 S2-A-03 原示例不含「风险」字样，仍保持订单+库存+生产三件套。"""
    plan = supervisor_agent.build_plan("分析订单O001能否按时完成")

    assert plan["intent_code"] == "order_delivery"
    assert plan["capabilities"] == ["order", "inventory", "production"]
    assert plan["risk_focus"] is False


def test_risk_report_available_for_plain_delivery_query():
    outcome = supervisor_agent.handle("分析订单O009能否按时完成")

    section = next(
        item for item in outcome["risk_report"]["sections"] if item["capability"] == "order"
    )
    assert section["risk"] == "high"
    assert outcome["risk_report"]["overall_risk"] == "high"


# --------------------------------------------------------------------------
# S2 审查修复：LLM 规划（默认优先，可注入客户端验证）
# --------------------------------------------------------------------------


def test_llm_planner_is_used_by_default_when_key_present(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    payload = json.dumps(
        {
            "capabilities": ["order", "inventory", "production", "equipment"],
            "order_ids": ["O002"],
            "intent": "订单交付与设备风险",
        },
        ensure_ascii=False,
    )

    plan = supervisor_agent.build_plan(
        "O002 这单会不会拖期",
        llm_client_factory=_fake_llm_factory(payload),
    )

    assert plan["planner"] == "rule+llm"
    assert plan["llm"]["requested"] == ["order", "inventory", "production", "equipment"]
    assert plan["llm"]["intent"] == "订单交付与设备风险"
    assert "O002" in plan["entities"]["order_ids"]
    assert set(plan["capabilities"]) >= {"order", "inventory", "production", "equipment"}


def test_llm_planner_drops_unregistered_capabilities(monkeypatch):
    """LLM 只能从注册表挑能力，越权能力必须被丢弃。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    payload = json.dumps(
        {"capabilities": ["quality", "delete_database", "equipment"]},
        ensure_ascii=False,
    )

    plan = supervisor_agent.build_plan(
        "看看质量缺陷怎么样",
        use_llm=True,
        llm_client_factory=_fake_llm_factory(payload),
    )

    assert plan["planner"] == "rule+llm"
    assert "delete_database" not in plan["capabilities"]
    assert set(plan["capabilities"]) == {"quality", "equipment"}
    assert all(step["agent"] in supervisor_agent.AGENT_DISPATCH for step in plan["steps"])


def test_llm_planner_cannot_remove_rule_capabilities(monkeypatch):
    """LLM 只增补不削减：风险类问题的五维能力不能被 LLM 砍掉。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    payload = json.dumps({"capabilities": ["order"]}, ensure_ascii=False)

    plan = supervisor_agent.build_plan(
        "帮我分析风险",
        use_llm=True,
        llm_client_factory=_fake_llm_factory(payload),
    )

    assert plan["planner"] == "rule+llm"
    assert plan["capabilities"] == [
        "order",
        "inventory",
        "production",
        "equipment",
        "quality",
    ]


def test_llm_invalid_response_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    plan = supervisor_agent.build_plan(
        "分析订单O001能否按时完成",
        use_llm=True,
        llm_client_factory=_fake_llm_factory("这不是 JSON"),
    )

    assert plan["planner"] == "rule"
    assert plan["capabilities"] == ["order", "inventory", "production"]
    assert any("回退规则规划" in note for note in plan["notes"])


def test_no_llm_switch_forces_rules_even_with_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    plan = supervisor_agent.build_plan(
        "分析订单O001能否按时完成",
        use_llm=False,
        llm_client_factory=_fake_llm_factory(json.dumps({"capabilities": ["quality"]})),
    )

    assert plan["planner"] == "rule"
    assert plan["capabilities"] == ["order", "inventory", "production"]
    assert any("--no-llm" in note for note in plan["notes"])


def test_llm_planner_without_key_never_calls_client():
    called = []

    def spy_factory(timeout=20):
        called.append(timeout)
        raise AssertionError("未配置 Key 时不应创建 LLM 客户端")

    plan = supervisor_agent.build_plan(
        "分析订单O001能否按时完成",
        llm_client_factory=spy_factory,
    )

    assert plan["planner"] == "rule"
    assert called == []
