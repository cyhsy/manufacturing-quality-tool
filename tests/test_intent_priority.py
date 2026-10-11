"""S6.1 测试：意图优先级模型（动作型 > 分析型）与用户目标识别。

覆盖：
- S6.1-A-01 意图优先级：动作型意图优先于分析型；优先级表覆盖全部意图编码；
- S6.1-A-02 用户目标识别：问题/风险 + 解决动作 -> 优化决策；
- S6.1-A-03 验收原文必须路由到 manufacturing_optimization，且既有路由不变；
- S6.1-A-04 一次任务的数据读取次数上限（重复调用Guard，Sprint 7 用 context_cache 优化）。
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from agents import supervisor_agent


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# S6.1-A-03 验收原文
ACCEPTANCE = "O001订单交付风险高，帮我制定优化方案"
TIGHT_INPUT = "10000件电机壳体，15天交付，帮我优化生产方案"


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY，避免规划类测试意外发起真实 LLM 调用。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


# --------------------------------------------------------------------------
# S6.1-A-03 验收原文与「以下不变」清单
# --------------------------------------------------------------------------


def test_acceptance_input_routes_to_manufacturing_optimization():
    """S6.1-A-03 验收原文：动作型意图必须胜过风险分析。"""
    plan = supervisor_agent.build_plan(ACCEPTANCE)

    assert plan["intent_code"] == "manufacturing_optimization"
    assert plan["task"] == "manufacturing_optimization"
    assert plan["capabilities"] == [
        "order",
        "production_planning",
        "equipment",
        "quality",
        "decision_fusion",
    ]
    assert plan["entities"]["order_id"] == "O001"


def test_mandated_unchanged_routes():
    """S6.1-A-03 要求保持不变的四条路由。"""
    expected = {
        "分析订单风险": "comprehensive_risk",
        "订单能否按时完成": "order_delivery",
        "制定生产计划": "production_planning",
        "优化生产方案": "manufacturing_optimization",
    }

    for text, intent in expected.items():
        assert supervisor_agent.build_plan(text)["intent_code"] == intent, text


def test_acceptance_executes_multi_agent_optimization():
    """验收原文要真正走多 Agent 协同（不只是路由正确）。"""
    outcome = supervisor_agent.handle(ACCEPTANCE, generate_report=False)

    assert outcome["intent_code"] == "manufacturing_optimization"
    assert set(outcome["results"]) == {
        "order_agent",
        "planning_agent",
        "equipment_agent",
        "quality_agent",
        "decision_engine",
    }
    assert outcome["decision"]["order"]["order_id"] == "O001"
    assert outcome["decision"]["recommendation"]["decision"] in {
        "execute",
        "trade_off",
        "escalate",
        "keep_plan",
    }
    json.dumps(outcome, ensure_ascii=False)


# --------------------------------------------------------------------------
# S6.1-A-01 意图优先级模型
# --------------------------------------------------------------------------


def test_intent_priority_covers_every_intent_code():
    """S6.1 回归教训：优先级表漏掉某个编码会让它掉到默认最低优先级而被兜底意图抢走。"""
    assert set(supervisor_agent.INTENT_PRIORITY) == set(supervisor_agent.INTENT_LABELS)
    assert set(supervisor_agent.ACTION_INTENTS) <= set(supervisor_agent.INTENT_PRIORITY)


def test_action_intents_outrank_analysis_intents():
    rank = supervisor_agent._intent_rank

    for action in supervisor_agent.ACTION_INTENTS:
        for analysis in ("comprehensive_risk", "order_delivery", "overview", "order_query"):
            assert rank(action) < rank(analysis), (action, analysis)


def test_intent_rank_order_follows_priority_list():
    rank = supervisor_agent._intent_rank
    ordered = supervisor_agent.INTENT_PRIORITY

    for index in range(len(ordered) - 1):
        current, following = ordered[index], ordered[index + 1]
        # 同为动作型或同为分析型时，顺序由 INTENT_PRIORITY 决定
        if (current in supervisor_agent.ACTION_INTENTS) == (
            following in supervisor_agent.ACTION_INTENTS
        ):
            assert rank(current) <= rank(following), (current, following)


def test_unknown_intent_code_falls_back_to_lowest_priority():
    assert supervisor_agent._intent_rank("not_an_intent")[1] == len(
        supervisor_agent.INTENT_PRIORITY
    )


def test_classify_collects_all_candidates_then_selects():
    """两阶段模型：命中集合与胜出意图解耦。"""
    entities = supervisor_agent.extract_entities(ACCEPTANCE)
    candidates = supervisor_agent.collect_intent_candidates(ACCEPTANCE, entities)

    assert "comprehensive_risk" in candidates  # 风险关键词命中
    assert "manufacturing_optimization" in candidates  # 解决动作 + 优化关键词命中
    assert "order_delivery" in candidates  # 订单实体命中

    code, _, capabilities, _ = supervisor_agent.select_intent(candidates)
    assert code == "manufacturing_optimization"
    assert capabilities == list(supervisor_agent.MANUFACTURING_OPTIMIZATION_CHAIN)


# --------------------------------------------------------------------------
# S6.1-A-02 用户目标识别（问题/风险 + 解决动作）
# --------------------------------------------------------------------------


def test_optimization_signals_are_defined():
    for signal in ("优化", "改善", "调整方案", "怎么解决", "怎么办", "制定方案", "降低风险", "提高效率"):
        assert signal in supervisor_agent.OPTIMIZATION_SIGNALS, signal


@pytest.mark.parametrize(
    "text",
    [
        "O001订单交付风险高，帮我制定优化方案",
        "订单风险高怎么办？",
        "如何降低延期风险",
        "质量风险高，怎么改善？",
        "交期缺口太大，帮我调整方案",
        "产能不足怎么解决",
    ],
)
def test_problem_plus_resolution_triggers_optimization(text):
    assert supervisor_agent.is_problem_and_resolution(text) is True
    assert supervisor_agent.build_plan(text)["intent_code"] == "manufacturing_optimization"


@pytest.mark.parametrize(
    "text",
    [
        "分析订单风险",
        "帮我分析风险",
        "订单有什么风险？",
        "看看质量缺陷情况",
        "分析一下质量下降的原因",
    ],
)
def test_analysis_phrasing_does_not_trigger_optimization(text):
    """只「分析」不「解决」时不得判为优化决策。"""
    assert supervisor_agent.is_problem_and_resolution(text) is False
    assert supervisor_agent.build_plan(text)["intent_code"] != "manufacturing_optimization"


def test_resolution_without_problem_is_not_optimization():
    """只有解决动作、没有问题/风险时不算优化决策（如「提高效率的指标定义」）。"""
    assert supervisor_agent.is_problem_and_resolution("提高效率的指标定义") is False


def test_device_fault_phrasing_keeps_equipment_intent():
    """设备类词不在问题信号里：设备故障诉求仍走设备故障诊断（含诊断与工单）。"""
    for text in ["CNC02报警了，帮我分析", "CNC02故障停机，怎么解决", "WELD02停机怎么办"]:
        assert supervisor_agent.build_plan(text)["intent_code"] == "equipment_failure", text


# --------------------------------------------------------------------------
# 全量路由回归矩阵
# --------------------------------------------------------------------------


def test_full_routing_matrix_is_unchanged():
    expected = {
        ACCEPTANCE: "manufacturing_optimization",
        "最近订单交付压力大，帮我优化生产方案": "manufacturing_optimization",
        TIGHT_INPUT: "manufacturing_optimization",
        "优化生产方案": "manufacturing_optimization",
        "这个订单怎么安排生产？": "production_planning",
        "10000件电机壳体，15天交付，怎么安排生产": "production_planning",
        "O009怎么排产": "production_planning",
        "制定生产计划": "production_planning",
        "分析订单O001能否按时完成": "order_delivery",
        "订单能否按时完成": "order_delivery",
        "CNC02报警了，帮我分析": "equipment_failure",
        "最近电机壳体良率下降，分析原因": "quality_issue_analysis",
        "支架尺寸偏大问题，批次LOT-202605-001": "quality_issue_analysis",
        "看看质量缺陷情况": "quality_query",
        "设备维保情况": "equipment_query",
        "设备有没有故障，顺便看下质量缺陷": "mixed_query",
        "库存够吗": "inventory_query",
        "分析订单风险": "comprehensive_risk",
        "帮我分析风险": "comprehensive_risk",
        "工厂收到10000件电机壳体订单，15天交付，帮我分析风险": "comprehensive_risk",
        "今天工厂什么情况": "overview",
        "今天产量下降": "overview",
    }

    for text, intent in expected.items():
        assert supervisor_agent.build_plan(text)["intent_code"] == intent, text


# --------------------------------------------------------------------------
# S6.1-A-04 重复调用检查（Guard；优化放 Sprint 7）
# --------------------------------------------------------------------------


def test_data_reads_per_optimization_task_are_bounded(monkeypatch):
    """一次优化任务的数据读取次数上限。

    当前实测：合计 45 次（quality.csv 11 / equipment.csv 10 / production.csv 7 /
    inventory.csv 6 / iot_sensor.csv 6 / orders.csv 4 / bom.csv 1）。
    本测试只做「不恶化」Guard；Sprint 7 引入 context_cache 后应降到每文件 1 次。
    """
    counts = {}
    original_read_csv = pd.read_csv

    def counting_read_csv(filepath_or_buffer, *args, **kwargs):
        try:
            name = Path(str(filepath_or_buffer)).name
        except (TypeError, ValueError):
            name = "stream"
        counts[name] = counts.get(name, 0) + 1
        return original_read_csv(filepath_or_buffer, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", counting_read_csv)

    supervisor_agent.handle(TIGHT_INPUT, generate_report=False)

    assert counts, "未捕获到任何数据读取"
    assert sum(counts.values()) <= 60, counts
    for name, count in counts.items():
        assert count <= 15, (name, count)

    assert {
        "quality.csv",
        "equipment.csv",
        "production.csv",
        "inventory.csv",
        "orders.csv",
        "bom.csv",
    } <= set(counts)
