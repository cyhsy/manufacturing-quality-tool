"""Supervisor Agent：意图解析 -> 执行计划 -> 子 Agent 调度（S2-A-03）。

处理流程：

    用户输入（如「分析订单O001能否按时完成」）
        ↓  resolve_capabilities()  规则（可选 LLM 辅助）
    能力集合（order + inventory + production）
        ↓  build_steps()
    执行计划（每一步 = 能力 + 归属 Agent + 动作 + 理由）
        ↓  execute_plan()
    各子 Agent 的结构化结果

设计要点（第一版，规则为主、不追求复杂）：

1. **能力注册表**：所有可调度能力集中在 ``CAPABILITIES``，Agent 名称不散落在判断逻辑中。
2. **依赖扩张**：订单「能否按时完成」必须同时看物料与产能，
   因此 ``order`` 会扩张为 ``order + inventory + production``（这正是任务书要求的三件套）。
3. **能力归属**：v1 的 ``agents/`` 只有 order / equipment / quality 三个执行 Agent，
   因此 ``inventory``、``production`` 两个能力由 ``order_agent`` 执行
   （订单可交付分析本身就要用库存与产能）；
   后续新增 ``production_agent`` 只需改 ``CAPABILITIES`` 中的 ``agent`` 字段。
4. **LLM 只做辅助**：LLM 只能从注册表里挑选能力，执行计划结构始终由本模块生成；
   未配置 Key、依赖缺失或调用失败时自动回退纯规则规划。
5. **单点失败不影响整体**：某个 Agent 抛异常时记录为该 Agent 的 error 结果，计划其余部分照常执行。
"""

import json
import os
import re

from agents import equipment_agent, order_agent, quality_agent


# --------------------------------------------------------------------------
# 能力注册表
# --------------------------------------------------------------------------

CAPABILITIES = {
    "order": {
        "label": "订单",
        "agent": "order_agent",
        "tool_module": "agent_tools.order_tools",
        "description": "订单信息与可交付能力",
    },
    "inventory": {
        "label": "库存",
        "agent": "order_agent",
        "tool_module": "agent_tools.inventory_tools",
        "description": "原材料库存与安全库存预警",
    },
    "production": {
        "label": "生产",
        "agent": "order_agent",
        "tool_module": "agent_tools.order_tools",
        "description": "MES 产线、瓶颈产能与良率",
    },
    "equipment": {
        "label": "设备",
        "agent": "equipment_agent",
        "tool_module": "agent_tools.equipment_tools",
        "description": "设备状态、维保与传感器告警",
    },
    "quality": {
        "label": "质量",
        "agent": "quality_agent",
        "tool_module": "agent_tools.quality_tools",
        "description": "缺陷统计、严重等级与根因（复用原有质量分析）",
    },
}

CAPABILITY_ORDER = ["order", "inventory", "production", "equipment", "quality"]

# 判定订单交付能力时，必须同时具备的能力
CAPABILITY_DEPENDENCIES = {
    "order": ("inventory", "production"),
}

INTENT_LABELS = {
    "order_delivery": "订单交付能力分析",
    "order_query": "订单查询",
    "inventory_query": "库存查询",
    "production_query": "生产能力查询",
    "equipment_query": "设备状态查询",
    "quality_query": "质量分析",
    "mixed_query": "综合运营查询",
    "overview": "制造运营总览",
}

INTENT_KEYWORDS = {
    "order": ("订单", "客户", "出货", "发货", "交货"),
    "inventory": ("库存", "物料", "缺料", "备料", "原材料", "安全库存"),
    "production": ("产能", "生产", "产线", "mes", "良率", "工序", "排产"),
    "equipment": ("设备", "故障", "维保", "保养", "停机", "传感器", "振动", "温度", "点检"),
    "quality": ("质量", "缺陷", "不良", "根因", "返工", "报废", "检验", "抽检"),
}

DELIVERY_KEYWORDS = (
    "能否",
    "能不能",
    "按时",
    "交付",
    "交期",
    "完成",
    "风险",
    "来不来得及",
)

# 订单编号形如 O001；用 [A-Za-z]\d{2,} 而不是 \bO\d+\b，
# 因为中文属于 \w，"订单O001" 中 O 前面没有词边界。
ORDER_ID_PATTERN = re.compile(r"[A-Za-z]\d{2,}")

LLM_SYSTEM_PROMPT = (
    "你是制造运营 Agent 的调度器。根据用户问题判断需要哪些能力，只输出 JSON。"
    '可选能力（只能从中选择）：["order","inventory","production","equipment","quality"]。'
    '输出格式：{"capabilities":["order","inventory","production"],'
    '"order_ids":["O001"],"intent":"订单交付能力分析"}。'
    "若问题涉及订单能否按时交付，必须同时包含 order、inventory、production。"
)


# --------------------------------------------------------------------------
# 意图与能力解析（规则）
# --------------------------------------------------------------------------


def _known_order_ids():
    """读取真实订单编号用于校验；数据不可用时返回空列表。"""
    from agent_tools import order_tools

    try:
        return order_tools.list_order_ids()
    except (FileNotFoundError, OSError, ValueError):
        return []


def extract_order_ids(text, known_order_ids=None):
    """从文本中提取订单编号。

    提供 ``known_order_ids`` 时只保留真实存在的编号，避免把无关的字母数字串当订单号。
    """
    candidates = {match.group(0).upper() for match in ORDER_ID_PATTERN.finditer(str(text))}
    if known_order_ids is None:
        return sorted(candidates)

    known = {str(value).upper() for value in known_order_ids}
    matched = candidates & known
    return sorted(matched) if matched else sorted(candidates)


def detect_capabilities(text):
    """按关键词粗判需要的能力（保持 CAPABILITY_ORDER 顺序）。"""
    lowered = str(text).lower()
    matched = {
        capability
        for capability, keywords in INTENT_KEYWORDS.items()
        if any(keyword.lower() in lowered for keyword in keywords)
    }
    return [capability for capability in CAPABILITY_ORDER if capability in matched]


def is_delivery_question(text):
    """是否在问「能否按时交付」这类问题（只看交付类关键词）。"""
    content = str(text)
    return any(keyword in content for keyword in DELIVERY_KEYWORDS)


def resolve_capabilities(text):
    """解析用户输入 -> (能力列表, 订单编号列表, 是否交付类问题, 是否总览兜底)。

    最后一个返回值用于区分「用户没提具体诉求，给出运营总览」与
    「用户确实同时问了多个能力」，两者意图不同。
    """
    capabilities = set(detect_capabilities(text))
    order_ids = extract_order_ids(text, _known_order_ids())
    delivery = bool(order_ids) or is_delivery_question(text)

    if order_ids or delivery:
        capabilities.add("order")

    # 交付能力必须同时看物料齐套性与瓶颈产能（任务书要求的三件套）
    if delivery:
        capabilities.update(CAPABILITY_DEPENDENCIES["order"])

    overview_fallback = not capabilities
    if overview_fallback:
        capabilities = set(CAPABILITIES)  # 未识别出具体诉求时给出运营总览

    ordered = [capability for capability in CAPABILITY_ORDER if capability in capabilities]
    return ordered, order_ids, delivery, overview_fallback


def classify_intent(capabilities, delivery, overview_fallback=False):
    """能力集合 -> 意图编码。"""
    if overview_fallback:
        return "overview"
    if delivery and "order" in capabilities:
        return "order_delivery"
    if len(capabilities) == 1:
        return f"{capabilities[0]}_query"
    if not capabilities:
        return "overview"
    return "mixed_query"


# --------------------------------------------------------------------------
# 执行计划
# --------------------------------------------------------------------------


def _action_for(capability, order_id):
    if capability == "order":
        return "analyze_order_delivery" if order_id else "analyze_orders_overview"
    return {
        "inventory": "get_inventory_summary",
        "production": "get_factory_capacity",
        "equipment": "analyze_equipment_status",
        "quality": "analyze_quality",
    }[capability]


def _reason_for(capability, order_ids):
    if capability == "order":
        if order_ids:
            return f"用户关注订单 {'、'.join(order_ids)} 的交付情况，需要订单基础信息"
        return "用户需要订单整体情况，需要订单基础信息"

    return {
        "inventory": "交付能力取决于物料齐套性，需要库存与安全库存状态",
        "production": "交付能力取决于瓶颈产能，需要 MES 产线与在产产能",
        "equipment": "用户关注设备可用性，需要设备台账、维保与传感器数据",
        "quality": "用户关注质量表现，需要缺陷统计与原有质量分析结果",
    }[capability]


def build_steps(capabilities, order_ids):
    """能力列表 -> 执行步骤，并返回上下文参数。"""
    order_id = order_ids[0] if order_ids else None
    entities = {"order_ids": list(order_ids)}
    if order_id:
        entities["order_id"] = order_id

    steps = []
    for index, capability in enumerate(capabilities, start=1):
        meta = CAPABILITIES[capability]
        step = {
            "step": index,
            "capability": capability,
            "capability_label": meta["label"],
            "agent": meta["agent"],
            "tool_module": meta["tool_module"],
            "action": _action_for(capability, order_id),
            "reason": _reason_for(capability, order_ids),
        }
        if capability in ("order", "inventory", "production") and order_id:
            step["arguments"] = {"order_id": order_id}
        steps.append(step)

    return steps, entities


def build_plan(user_input, use_llm=False):
    """生成执行计划（规则为主，可选 LLM 辅助选择能力）。

    参数：
        user_input: 用户输入文本。
        use_llm:    True 时尝试用 LLM 辅助选择能力；失败自动回退规则。

    返回 dict：
        user_input, intent, intent_code, capabilities, entities, steps, planner, notes
    """
    text = str(user_input or "").strip()
    capabilities, order_ids, delivery, overview_fallback = resolve_capabilities(text)
    intent_code = classify_intent(capabilities, delivery, overview_fallback)
    steps, entities = build_steps(capabilities, order_ids)

    plan = {
        "user_input": text,
        "intent": INTENT_LABELS.get(intent_code, intent_code),
        "intent_code": intent_code,
        "capabilities": capabilities,
        "entities": entities,
        "steps": steps,
        "planner": "rule",
        "notes": [],
    }

    if use_llm:
        llm_result = _llm_plan(text)
        if llm_result and llm_result.get("capabilities"):
            llm_capabilities = [
                capability
                for capability in CAPABILITY_ORDER
                if capability in set(llm_result["capabilities"])
            ]
            if llm_capabilities:
                llm_order_ids = llm_result.get("order_ids") or order_ids
                llm_delivery = delivery or bool(llm_order_ids)
                if llm_delivery and "order" in llm_capabilities:
                    llm_capabilities = [
                        capability
                        for capability in CAPABILITY_ORDER
                        if capability in set(llm_capabilities)
                        | set(CAPABILITY_DEPENDENCIES["order"])
                    ]
                intent_code = classify_intent(llm_capabilities, llm_delivery)
                steps, entities = build_steps(llm_capabilities, llm_order_ids)
                plan.update(
                    {
                        "intent": INTENT_LABELS.get(intent_code, intent_code),
                        "intent_code": intent_code,
                        "capabilities": llm_capabilities,
                        "entities": entities,
                        "steps": steps,
                        "planner": "rule+llm",
                        "notes": [f"LLM 辅助规划：{llm_result.get('llm_intent') or '已选择能力'}"],
                    }
                )
        if plan["planner"] == "rule":
            plan["notes"].append(
                "LLM 辅助规划不可用（未配置 DEEPSEEK_API_KEY、依赖缺失或调用失败），已回退规则规划"
            )

    return plan


def explain_plan(plan):
    """把执行计划转成人类可读文本（CLI 输出用）。"""
    lines = [
        f"用户输入：{plan['user_input']}",
        f"意图：{plan['intent']}（{plan['intent_code']}）",
        f"规划方式：{plan['planner']}",
        "执行计划：",
    ]
    for step in plan["steps"]:
        lines.append(
            f"  {step['step']}. [{step['capability_label']}] {step['agent']} -> {step['action']}"
            f"（{step['reason']}）"
        )
    for note in plan.get("notes", []):
        lines.append(f"备注：{note}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# LLM 辅助规划（可选，失败即回退）
# --------------------------------------------------------------------------


def _llm_plan(user_input, timeout=20):
    """可选 LLM 规划：只返回「能力选择」建议，失败返回 None。

    安全约束：LLM 只能从 ``CAPABILITIES`` 注册表中选择能力，且执行计划结构
    始终由本模块生成，LLM 不产出可执行步骤本身。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    base_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip() or "https://api.deepseek.com"
    model = os.environ.get("DEEPSEEK_MODEL", "").strip() or "deepseek-v4-flash"

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": str(user_input)},
            ],
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content)
    except Exception:  # noqa: BLE001 - LLM 属于可选增强，任何失败都回退规则
        return None

    raw_capabilities = payload.get("capabilities")
    if not isinstance(raw_capabilities, list):
        return None

    capabilities = [
        str(value) for value in raw_capabilities if str(value) in CAPABILITIES
    ]
    if not capabilities:
        return None

    raw_order_ids = payload.get("order_ids")
    order_ids = []
    if isinstance(raw_order_ids, list):
        known = {value.upper() for value in _known_order_ids()}
        for value in raw_order_ids:
            candidate = str(value).upper()
            if not known or candidate in known:
                order_ids.append(candidate)

    return {
        "capabilities": capabilities,
        "order_ids": order_ids,
        "llm_intent": payload.get("intent"),
    }


# --------------------------------------------------------------------------
# 调度执行
# --------------------------------------------------------------------------

AGENT_DISPATCH = {
    "order_agent": order_agent.run,
    "equipment_agent": equipment_agent.run,
    "quality_agent": quality_agent.run,
}


def execute_plan(plan):
    """按计划调度子 Agent。

    同一个 Agent 的多个能力会被合并成一次调用；单个 Agent 失败时只记录该 Agent 的
    error 结果，不影响计划中其它 Agent 的执行。
    """
    grouped = {}
    for step in plan["steps"]:
        grouped.setdefault(step["agent"], []).append(step["capability"])

    arguments = dict(plan.get("entities") or {})
    results = {}

    for agent_name, capabilities in grouped.items():
        runner = AGENT_DISPATCH.get(agent_name)
        if runner is None:
            results[agent_name] = {
                "agent": agent_name,
                "status": "error",
                "reason": f"未注册的 Agent：{agent_name}",
            }
            continue

        try:
            results[agent_name] = runner(capabilities=capabilities, arguments=arguments)
        except Exception as exc:  # noqa: BLE001 - 单点失败不影响整体计划
            results[agent_name] = {
                "agent": agent_name,
                "status": "error",
                "capabilities": capabilities,
                "reason": f"{type(exc).__name__}: {exc}",
            }

    return {"plan": plan, "results": results}


def handle(user_input, use_llm=False):
    """Supervisor 主入口：生成执行计划并执行，返回计划与各 Agent 结果。"""
    plan = build_plan(user_input, use_llm=use_llm)
    execution = execute_plan(plan)
    return {
        "user_input": plan["user_input"],
        "plan": plan,
        "results": execution["results"],
    }


def main():
    """命令行入口。

    示例：
        python -m agents.supervisor_agent 分析订单O001能否按时完成
        python -m agents.supervisor_agent --plan-only 设备有没有故障
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Supervisor Agent：生成执行计划并调度子 Agent"
    )
    parser.add_argument("query", nargs="*", help="用户输入，例如：分析订单O001能否按时完成")
    parser.add_argument("--llm", action="store_true", help="启用 LLM 辅助规划（需 DEEPSEEK_API_KEY）")
    parser.add_argument("--plan-only", action="store_true", help="只输出执行计划，不执行子 Agent")
    args = parser.parse_args()

    user_input = " ".join(args.query).strip() or "分析订单O001能否按时完成"
    plan = build_plan(user_input, use_llm=args.llm)

    print(explain_plan(plan))
    print()

    if args.plan_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    execution = execute_plan(plan)
    print(json.dumps(execution["results"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
