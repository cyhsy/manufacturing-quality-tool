"""S6-A 测试：制造运营优化（多 Agent 协同）/ 决策融合 / 成本模型 / 决策报告。

覆盖：
- S6-A-03 成本模型：加急采购、加班、换线、延期成本，以及分层（模型在 modules/cost_model.py）；
- S6-A-02 决策融合：四类风险融合、措施逐项累计节省、成本与收益、推荐结论；
- S6-A-01 多 Agent 协同任务 manufacturing_optimization（5 步 + 依赖关系），且既有路由不被破坏；
- S6-A-04 制造决策报告：Markdown 结构、内容、命名与覆盖规则。
"""

import json
from datetime import date
from pathlib import Path

import pytest

from agent_tools import cost_tools, planning_tools
from agents import supervisor_agent
from modules import cost_model, decision_engine, planning_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TODAY = "2026-10-11"

# Sprint 6 验收输入
PRESSURE_INPUT = "最近订单交付压力大，帮我优化生产方案"
# 紧张场景：计划工期超出交期，可复现完整「优化方案 / 预计 / 成本 / 收益」叙事
TIGHT_INPUT = "10000件电机壳体，15天交付，帮我优化生产方案"


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY，避免规划类测试意外发起真实 LLM 调用。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


# --------------------------------------------------------------------------
# S6-A-03 成本模型
# --------------------------------------------------------------------------


def test_expedite_purchase_cost():
    result = cost_tools.expedite_purchase_cost(
        [{"material": "铝合金", "shortage": 20000, "unit": "kg"}]
    )

    assert result["amount"] == 35200.0  # 20000 kg × 22 元 × 8%
    assert result["items"][0]["cost_item"] == "加急采购费（铝合金）"
    assert "8%" in result["items"][0]["detail"]


def test_expedite_purchase_cost_ignores_materials_without_shortage():
    result = cost_tools.expedite_purchase_cost(
        [{"material": "铝合金", "shortage": 0, "unit": "kg"}]
    )

    assert result["amount"] == 0
    assert result["items"] == []


def test_overtime_and_setup_cost():
    overtime = cost_tools.overtime_cost(stage_count=4, production_days=8)
    assert overtime["amount"] == 32000.0  # 4 × 8 × 1000

    setup = cost_tools.equipment_setup_cost(1)
    assert setup["amount"] == 3000.0

    assert cost_tools.equipment_setup_cost(0)["amount"] == 0


def test_delay_cost():
    result = cost_tools.delay_cost(2)

    assert result["amount"] == 74000.0  # 2 × (12000 + 25000)
    assert result["days"] == 2
    assert cost_tools.delay_cost(0)["amount"] == 0


def test_cost_rates_are_exposed():
    rates = cost_tools.get_cost_rates()

    assert rates["expedite_fee_rate"] == cost_model.EXPEDITE_FEE_RATE
    assert rates["shift_stage_daily_cost"] == cost_model.SHIFT_STAGE_DAILY_COST
    assert "铝合金" in rates["material_unit_price"]


def test_cost_tool_wraps_module_layer():
    """分层：成本模型在 modules/cost_model.py，agent_tools/cost_tools.py 只做包装。"""
    source = (PROJECT_ROOT / "agent_tools" / "cost_tools.py").read_text(encoding="utf-8")

    assert "from modules import cost_model" in source

    # 包装层不得重新定义费率常量，避免出现第二套成本口径
    for constant in (
        "EXPEDITE_FEE_RATE",
        "SHIFT_STAGE_DAILY_COST",
        "EQUIPMENT_SETUP_COST",
        "DELAY_PENALTY_PER_DAY",
        "MATERIAL_UNIT_PRICE",
    ):
        assert f"{constant} =" not in source, constant


# --------------------------------------------------------------------------
# S6-A-02 决策融合
# --------------------------------------------------------------------------


def test_simulate_scenario_applies_measures_cumulatively():
    plan = planning_tools.generate_production_plan(
        product="电机壳体", quantity=10000, delivery_days=15, today=TODAY
    )
    stages = plan["capacity"]["stages"]
    material_days = plan["timeline"]["material_days"]

    baseline = planning_engine.simulate_scenario(stages, 10000, material_days, [])
    assert baseline["total_days"] == 17

    express = planning_engine.simulate_scenario(
        stages, 10000, material_days, [{"type": "express_purchase"}]
    )
    assert express["purchase_days"] == 1
    assert express["total_days"] == 15

    with_equipment = planning_engine.simulate_scenario(
        stages,
        10000,
        material_days,
        [
            {"type": "express_purchase"},
            {"type": "enable_equipment", "process": "CNC加工", "capacity": 850},
        ],
    )
    assert with_equipment["total_days"] == 11

    with_shift = planning_engine.simulate_scenario(
        stages,
        10000,
        material_days,
        [
            {"type": "express_purchase"},
            {"type": "enable_equipment", "process": "CNC加工", "capacity": 850},
            {"type": "shift", "ratio": 0.3},
        ],
    )
    assert with_shift["total_days"] == 9


def test_decision_fuses_risks_measures_and_cost_for_tight_plan():
    outcome = supervisor_agent.handle(TIGHT_INPUT, generate_report=False)
    decision = outcome["decision"]

    assert decision["baseline"]["total_days"] == 17
    assert decision["baseline"]["available_days"] == 15
    assert decision["baseline"]["feasible"] is False

    applicable = [row for row in decision["measures"] if row["applicable"]]
    assert [row["type"] for row in applicable] == [
        "express_purchase",
        "enable_equipment",
        "shift",
    ]
    assert [row["days_saved"] for row in applicable] == [2, 4, 2]
    assert [row["total_days_after"] for row in applicable] == [15, 11, 9]

    assert decision["optimized"]["total_days"] == 9
    assert decision["optimized"]["days_saved"] == 8
    assert decision["optimized"]["feasible"] is True

    assert decision["cost"]["increase"] == 70200.0
    assert decision["cost"]["benefit"]["avoided_delay_days"] == 2
    assert decision["cost"]["benefit"]["avoided_amount"] == 74000.0
    assert decision["cost"]["net"] == 3800.0

    assert decision["recommendation"]["decision"] == "execute"
    assert decision["recommendation"]["label"] == "建议执行"
    assert len(decision["recommendation"]["actions"]) >= 3

    json.dumps(decision, ensure_ascii=False)


def test_decision_equipment_measure_targets_bottleneck():
    outcome = supervisor_agent.handle(TIGHT_INPUT, generate_report=False)
    measure = next(
        row for row in outcome["decision"]["measures"] if row["type"] == "enable_equipment"
    )

    assert measure["process"] == "CNC加工"
    assert measure["equipments"] == ["CNC03"]
    assert measure["adds_capacity"] == "800 → 1650 件/天"


def test_decision_keeps_plan_when_baseline_is_feasible():
    """最紧张的在手订单（O001）本身可行 -> 措施标为可选，不编造延期风险。"""
    outcome = supervisor_agent.handle(PRESSURE_INPUT, generate_report=False)
    decision = outcome["decision"]

    assert decision["baseline"]["feasible"] is True
    assert decision["optimized"]["feasible"] is True
    assert decision["recommendation"]["decision"] == "keep_plan"
    assert "无需优化" in decision["recommendation"]["reason"]
    assert "可选优化" in decision["recommendation"]["reason"]

    # 高优先级订单已按加急采购，不应再出现加急措施
    assert all(row["type"] != "express_purchase" for row in decision["measures"])
    assert decision["cost"]["benefit"]["avoided_amount"] == 0
    assert decision["recommendation"]["optimized_feasible"] is True


def test_decision_risk_profile_covers_four_dimensions():
    outcome = supervisor_agent.handle(PRESSURE_INPUT, generate_report=False)
    risks = outcome["decision"]["risks"]

    for key in ("order", "quality", "equipment", "plan"):
        assert risks[key]["risk"] in {"low", "medium", "high"}, key
    assert risks["overall"] in {"low", "medium", "high"}
    assert risks["notes"]


def test_decision_handles_empty_plan():
    decision = decision_engine.build_decision({"timeline": {}, "capacity": {}, "material": {}})

    assert decision["baseline"]["total_days"] is None
    assert decision["measures"] == []
    assert decision["cost"]["increase"] == 0
    assert decision["recommendation"]["decision"] == "escalate"


# --------------------------------------------------------------------------
# S6-A-01 制造运营优化（多 Agent 协同）
# --------------------------------------------------------------------------


def test_supervisor_defines_multi_agent_optimization_task():
    plan = supervisor_agent.build_plan(PRESSURE_INPUT)

    assert plan["intent_code"] == "manufacturing_optimization"
    assert plan["task"] == "manufacturing_optimization"
    assert plan["capabilities"] == [
        "order",
        "production_planning",
        "equipment",
        "quality",
        "decision_fusion",
    ]
    assert len(plan["steps"]) == 5
    assert [step["agent"] for step in plan["steps"]] == [
        "order_agent",
        "planning_agent",
        "equipment_agent",
        "quality_agent",
        "decision_engine",
    ]
    assert [step["action"] for step in plan["steps"]][-1] == "build_decision"

    # 决策步骤依赖前面全部步骤；其余步骤各自独立
    assert plan["steps"][4]["depends_on"] == [1, 2, 3, 4]
    assert all(step["depends_on"] == [] for step in plan["steps"][:4])


def test_optimization_task_executes_all_agents_in_order():
    outcome = supervisor_agent.handle(PRESSURE_INPUT, generate_report=False)

    assert set(outcome["results"]) == {
        "order_agent",
        "planning_agent",
        "equipment_agent",
        "quality_agent",
        "decision_engine",
    }
    for name in ("order_agent", "planning_agent", "equipment_agent", "quality_agent"):
        assert outcome["results"][name]["status"] == "ok", name
    assert outcome["results"]["decision_engine"]["status"] == "ok"
    assert outcome["results"]["decision_engine"]["capabilities"] == ["decision_fusion"]

    titles = [section["title"] for section in outcome["risk_report"]["sections"]]
    assert titles == [
        "订单交付风险",
        "生产计划风险",
        "设备风险",
        "质量风险",
        "综合决策",
    ]


def test_optimization_uses_most_tight_order_when_not_specified():
    outcome = supervisor_agent.handle(PRESSURE_INPUT, generate_report=False)
    planning_step = outcome["results"]["planning_agent"]

    assert planning_step["request"]["order_id"] == "O001"
    assert planning_step["assumptions"]
    assert outcome["decision"]["order"]["order_id"] == "O001"


def test_optimization_routing_does_not_break_existing_intents():
    expected = {
        "这个订单怎么安排生产？": "production_planning",
        "10000件电机壳体，15天交付，怎么安排生产": "production_planning",
        "分析订单O001能否按时完成": "order_delivery",
        "CNC02报警了，帮我分析": "equipment_failure",
        "最近电机壳体良率下降，分析原因": "quality_issue_analysis",
        "看看质量缺陷情况": "quality_query",
        "帮我分析风险": "comprehensive_risk",
        "今天工厂什么情况": "overview",
        "库存够吗": "inventory_query",
    }

    for text, intent in expected.items():
        assert supervisor_agent.build_plan(text)["intent_code"] == intent, text


def test_optimization_handles_unplannable_request():
    """给了产品但缺数量时，优化任务应返回可读结论而不是崩溃。"""
    outcome = supervisor_agent.handle("电机壳体怎么优化生产方案", generate_report=False)

    assert outcome["intent_code"] == "manufacturing_optimization"
    decision_step = outcome["results"]["decision_engine"]
    assert decision_step["status"] == "error"
    assert decision_step["decision"] is None
    assert "缺少产品与数量" in decision_step["reason"]
    assert "decision" not in outcome


# --------------------------------------------------------------------------
# S6-A-04 制造决策报告
# --------------------------------------------------------------------------


def test_decision_report_written_with_expected_structure(tmp_path):
    outcome = supervisor_agent.handle(TIGHT_INPUT, reports_dir=str(tmp_path))

    report_path = Path(outcome["report_path"])
    assert report_path.parent == tmp_path
    assert report_path.is_file()

    stamp = date.today().strftime("%Y%m%d")
    assert report_path.name == f"manufacturing_decision_电机壳体_{stamp}.md"

    markdown = report_path.read_text(encoding="utf-8")
    assert markdown == outcome["decision_report"]

    for section in [
        "# 制造决策报告",
        "## 一、当前方案",
        "## 二、风险",
        "## 三、优化方案",
        "## 四、预计",
        "## 五、综合建议",
        "## 六、数据来源与口径",
    ]:
        assert section in markdown, section

    for token in [
        "17 天",
        "15 天",
        "9 天",
        "70,200 元",
        "74,000 元",
        "3,800 元",
        "建议执行",
        "加急采购",
        "CNC03",
        "增加班次",
        "成本明细",
    ]:
        assert token in markdown, token


def test_decision_report_overwrites_instead_of_accumulating(tmp_path):
    first = supervisor_agent.handle(TIGHT_INPUT, reports_dir=str(tmp_path))
    second = supervisor_agent.handle(TIGHT_INPUT, reports_dir=str(tmp_path))

    assert first["report_path"] == second["report_path"]
    assert len(list(Path(tmp_path).glob("*.md"))) == 1


def test_decision_report_skipped_when_disabled(tmp_path):
    outcome = supervisor_agent.handle(TIGHT_INPUT, generate_report=False, reports_dir=str(tmp_path))

    assert outcome["report_path"] is None
    assert list(Path(tmp_path).glob("*.md")) == []


def test_reports_directory_ships_readme_and_examples():
    reports_dir = PROJECT_ROOT / "reports"

    assert (reports_dir / "README.md").is_file()
    assert list(reports_dir.glob("manufacturing_decision_*.md"))


def test_optimization_outputs_are_json_serializable(tmp_path):
    outcome = supervisor_agent.handle(TIGHT_INPUT, reports_dir=str(tmp_path))

    assert json.dumps(outcome, ensure_ascii=False)
