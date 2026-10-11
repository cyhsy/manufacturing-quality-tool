"""Supervisor Agent：意图解析 -> 执行计划 -> 子 Agent 调度（S2-A-03）。

处理流程：

    用户输入（如「工厂收到10000件电机壳体订单，15天交付，帮我分析风险」）
        ↓  extract_entities()   订单编号 / 产品 / 数量 / 交期
        ↓  classify()           意图（INTENT_RULES，可选 LLM 增补能力）
    能力集合（风险类问题 = 订单+库存+生产+设备+质量）
        ↓  build_steps()
    执行计划（每一步 = 能力 + 归属 Agent + 动作 + 理由）
        ↓  execute_plan()
    各子 Agent 结果 + 分段风险报告（build_risk_report）

设计要点（针对 S2 审查意见）：

1. **不是「关键词直连工具」**：先把输入归类到「意图」（``INTENT_RULES``），
   再由意图决定能力集合；同时抽取实体（订单号 / 产品 / 数量 / 交期天数），
   口述订单同样能回答「这一单有没有风险」。
2. **风险类问题走五维综合风险**：验收要求风险问答输出「质量风险」「设备风险」，
   因此 ``comprehensive_risk`` 会调用全部 5 个能力，并把结果组织成分段风险报告。
   任务书 S2-A-03 的原示例（不含「风险」字样）仍保持订单+库存+生产三件套。
3. **LLM 优先、规则兜底**：``use_llm=None``（默认）表示「配置了 DEEPSEEK_API_KEY 就用 LLM
   规划，否则用规则」；LLM 只在规则结果上做**并集增补**，不会削减规则判定的能力，
   避免漏选关键维度。``--no-llm`` 可强制纯规则。
4. **能力归属**：v1 的 ``agents/`` 只有 order / equipment / quality 三个执行 Agent，
   因此「库存」「生产」由 ``order_agent`` 执行；新增 ``production_agent``
   只需改 ``CAPABILITIES`` 中的 ``agent`` 字段。
5. **单点失败不影响整体**：某个 Agent 抛异常时记录为该 Agent 的 error 结果。
"""

import json
import os
import re

from agent_tools import equipment_tools, order_tools, quality_tools
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
    "quality_issue_analysis": {
        "label": "质量议题",
        "agent": "quality_agent",
        "tool_module": "agent_tools.quality_tools",
        "description": "质量议题分析：产品/缺陷/时间 + 质量追溯 + 改善知识库（S4-A-01）",
    },
    "equipment_failure": {
        "label": "设备故障",
        "agent": "equipment_agent",
        "tool_module": "agent_tools.equipment_tools",
        "description": "单台设备故障诊断（台账 + 传感器 + 故障知识库 + 维修工单）",
    },
}

# 五个运营维度：用于「综合风险 / 运营总览」（不包含单台设备/单议题动作能力）
CAPABILITY_ORDER = ["order", "inventory", "production", "equipment", "quality"]

# 动作能力：只在用户指向具体设备或具体质量议题时启用
ACTION_CAPABILITIES = ["equipment_failure", "quality_issue_analysis"]

# 全部能力（排序与筛选用）
ALL_CAPABILITY_ORDER = CAPABILITY_ORDER + ACTION_CAPABILITIES

# 交付类问题必须同时具备的能力（订单信息 + 物料齐套性 + 瓶颈产能）
DELIVERY_CAPABILITIES = ("order", "inventory", "production")

INTENT_LABELS = {
    "comprehensive_risk": "工厂综合风险分析",
    "order_delivery": "订单交付能力分析",
    "equipment_failure": "设备故障诊断",
    "quality_issue_analysis": "质量议题分析",
    "equipment_query": "设备状态查询",
    "quality_query": "质量分析",
    "inventory_query": "库存查询",
    "production_query": "生产能力查询",
    "order_query": "订单查询",
    "mixed_query": "综合运营查询",
    "overview": "制造运营总览",
}

# 意图规则（按顺序匹配，第一条命中即用）
INTENT_RULES = (
    {
        "code": "comprehensive_risk",
        "keywords": ("风险", "隐患", "有没有问题", "出问题", "会不会出"),
        "capabilities": tuple(CAPABILITY_ORDER),
        "reason": "风险类问题需要交付、库存、生产、设备、质量五个维度共同支撑",
    },
    {
        "code": "order_delivery",
        "keywords": ("能否", "能不能", "按时", "交付", "交期", "完成", "来不来得及", "拖期"),
        "capabilities": DELIVERY_CAPABILITIES,
        "reason": "交付能力取决于订单信息、物料齐套性与瓶颈产能",
    },
    {
        # 单台设备故障诊断：必须同时命中「故障类关键词」与「具体设备编号」
        "code": "equipment_failure",
        "keywords": ("报警", "告警", "故障", "停机", "异常", "诊断", "维修", "坏", "异响", "过热"),
        "capabilities": ("equipment_failure",),
        "requires_entity": "equipment_id",
        "reason": "用户指向具体设备的故障现象，按单台设备故障诊断 + 维修工单处理",
    },
    {
        # 质量议题分析（S4-A-04）：质量下降 / 缺陷上升类问题
        "code": "quality_issue_analysis",
        "keywords": (
            "质量下降",
            "质量变差",
            "质量恶化",
            "质量趋势",
            "质量波动",
            "质量异常",
            "不良上升",
            "不良率",
            "缺陷上升",
            "缺陷率",
            "客诉",
            "投诉",
        ),
        "capabilities": ("quality_issue_analysis",),
        "reason": "用户报告质量下降/异常，需要按产品、缺陷与时间做议题分析、追溯与改善建议",
    },
    {
        "code": "overview",
        "keywords": ("什么情况", "整体情况", "概况", "总览", "overview"),
        "capabilities": tuple(CAPABILITY_ORDER),
        "reason": "用户要求整体概览，返回全部维度的当前状态",
    },
)

# 细分意图用关键词（仅在 INTENT_RULES 未命中时使用）
INTENT_KEYWORDS = {
    "order": ("订单", "客户", "出货", "发货", "交货"),
    "inventory": ("库存", "物料", "缺料", "备料", "原材料", "安全库存"),
    "production": ("产能", "生产", "产线", "mes", "良率", "工序", "排产"),
    "equipment": ("设备", "故障", "维保", "保养", "停机", "传感器", "振动", "温度", "点检"),
    "quality": ("质量", "缺陷", "不良", "根因", "返工", "报废", "检验", "抽检"),
}

# 订单编号形如 O001；用 [A-Za-z]\d{2,} 而不是 \bO\d+\b，
# 因为中文属于 \w，"订单O001" 中 O 前面没有词边界。
ORDER_ID_PATTERN = re.compile(r"[A-Za-z]\d{2,}")
# 设备编号形如 CNC02 / WELD02 / CAST01，需与真实设备台账比对后采用
EQUIPMENT_ID_PATTERN = re.compile(r"[A-Z]{2,}\d{2,}")
QUANTITY_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:件|个|台|套|只|pcs|PCS)")
DAYS_PATTERN = re.compile(r"(\d+)\s*(?:天|日)")
WEEKS_PATTERN = re.compile(r"(\d+)\s*(?:周|星期)")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

LLM_SYSTEM_PROMPT = (
    "你是制造运营 Agent 的调度器。根据用户问题判断需要哪些能力，只输出 JSON。"
    '可选能力（只能从中选择）：["order","inventory","production","equipment","quality"]。'
    '输出格式：{"capabilities":["order","inventory","production"],'
    '"order_ids":["O001"],"intent":"订单交付能力分析"}。'
    "若问题涉及订单能否按时交付，必须同时包含 order、inventory、production。"
    "若问题涉及风险，应包含全部五个能力。"
)

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

# 批次号形如 LOT-202605-001
BATCH_PATTERN = re.compile(r"LOT-[A-Za-z0-9-]+", re.IGNORECASE)

RISK_ORDER = ["low", "medium", "high"]

SECTION_TITLES = {
    "order": "订单交付风险",
    "inventory": "物料库存风险",
    "production": "产能风险",
    "equipment": "设备风险",
    "equipment_failure": "设备故障风险",
    "quality": "质量风险",
    "quality_issue_analysis": "质量议题风险",
}


# --------------------------------------------------------------------------
# 实体抽取（订单号 / 产品 / 数量 / 交期）
# --------------------------------------------------------------------------


def _known_order_ids():
    """读取真实订单编号用于校验；数据不可用时返回空列表。"""
    try:
        return order_tools.list_order_ids()
    except (FileNotFoundError, OSError, ValueError):
        return []


def _known_products():
    """读取真实产品名称用于匹配；数据不可用时返回空列表。"""
    try:
        return order_tools.list_products()
    except (FileNotFoundError, OSError, ValueError):
        return []


def _known_equipment_ids():
    """读取真实设备编号用于匹配；数据不可用时返回空列表。"""
    try:
        return [
            str(record["equipment_id"])
            for record in equipment_tools.get_equipment_records()
        ]
    except (FileNotFoundError, OSError, ValueError):
        return []


def extract_order_ids(text, known_order_ids=None):
    """从文本中提取订单编号。

    提供 ``known_order_ids`` 且其中确有可比对的编号时，只返回真实存在的订单号；
    否则设备编号（如 CNC02）会被 ``[A-Za-z]\\d{2,}`` 误判为订单编号。
    """
    candidates = {match.group(0).upper() for match in ORDER_ID_PATTERN.finditer(str(text))}
    if known_order_ids is None:
        return sorted(candidates)

    known = {str(value).upper() for value in known_order_ids}
    if known:
        return sorted(candidates & known)

    return sorted(candidates)


def extract_equipment_ids(text, known_equipment_ids=None):
    """从文本中提取设备编号（如 CNC02），只保留台账中真实存在的设备。"""
    candidates = {match.group(0).upper() for match in EQUIPMENT_ID_PATTERN.finditer(str(text))}
    if known_equipment_ids is None:
        return sorted(candidates)

    known = {str(value).upper() for value in known_equipment_ids}
    if known:
        return sorted(candidates & known)

    return sorted(candidates)


def _known_defect_types():
    """质量数据的缺陷类型（用于实体识别）。"""
    try:
        return quality_tools.list_defect_options()
    except (FileNotFoundError, OSError, ValueError):
        return []


def _known_parts():
    """质量数据的零件名称（用于实体识别）。"""
    try:
        return quality_tools.list_part_options()
    except (FileNotFoundError, OSError, ValueError):
        return []


def _known_processes():
    """可选工序：质量数据工序 ∪ MES 工序。"""
    try:
        return quality_tools.list_process_options()
    except (FileNotFoundError, OSError, ValueError):
        return []


def extract_named_value(text, candidates):
    """在文本中匹配候选名称（长名优先），未命中返回 None。"""
    content = str(text)
    for name in sorted(candidates, key=lambda item: (-len(item), item)):
        if name and name in content:
            return name
    return None


def extract_part_name(text, candidates, product_name=None):
    """匹配质量数据的零件名称。

    「支架」是「涡轮支架」的子串：若该零件名只出现在已识别的产品名内部，
    则不视为独立零件，避免把产品名误判为零件名。
    """
    content = str(text)
    for name in sorted(candidates, key=lambda item: (-len(item), item)):
        if not name or name not in content:
            continue
        if product_name and name in product_name:
            remainder = content.replace(product_name, "")
            if name not in remainder:
                continue
        return name
    return None


def _first_number(pattern, text):
    match = pattern.search(str(text))
    if not match:
        return None
    value = float(match.group(1))
    return int(value) if value.is_integer() else value


def extract_product(text, known_products=None):
    """从文本中匹配已知产品名（长名优先，避免子串误配）。"""
    content = str(text)
    for name in known_products if known_products is not None else _known_products():
        if name and name in content:
            return name
    return None


def extract_entities(text, today=None):
    """抽取请求实体：订单编号、设备编号、产品、数量、交期天数或具体日期。"""
    content = str(text or "")

    order_ids = extract_order_ids(content, _known_order_ids())
    equipment_ids = extract_equipment_ids(content, _known_equipment_ids())
    product = extract_product(content)
    quantity = _first_number(QUANTITY_PATTERN, content)

    delivery_days = _first_number(DAYS_PATTERN, content)
    if delivery_days is None:
        weeks = _first_number(WEEKS_PATTERN, content)
        if weeks is not None:
            delivery_days = int(weeks) * 7

    date_match = DATE_PATTERN.search(content)
    deadline = date_match.group(0) if date_match else None

    product = extract_product(content)
    batch_match = BATCH_PATTERN.search(content)

    entities = {
        "order_ids": order_ids,
        "order_id": order_ids[0] if order_ids else None,
        "equipment_ids": equipment_ids,
        "equipment_id": equipment_ids[0] if equipment_ids else None,
        "product": product,
        "part_name": extract_part_name(content, _known_parts(), product_name=product),
        "defect_type": extract_named_value(content, _known_defect_types()),
        "process": extract_named_value(content, _known_processes()),
        "batch": batch_match.group(0) if batch_match else None,
        "quantity": quantity,
        "delivery_days": None if delivery_days is None else int(delivery_days),
        "deadline": deadline,
    }
    if today is not None:
        entities["today"] = str(today)
    return entities


# --------------------------------------------------------------------------
# 意图分类与执行计划
# --------------------------------------------------------------------------


def detect_capabilities(text):
    """按关键词粗判能力（仅在意图规则未命中时用于细分意图）。"""
    lowered = str(text).lower()
    matched = {
        capability
        for capability, keywords in INTENT_KEYWORDS.items()
        if any(keyword.lower() in lowered for keyword in keywords)
    }
    return [capability for capability in CAPABILITY_ORDER if capability in matched]


def _label_for(intent_code):
    if intent_code in INTENT_LABELS:
        return INTENT_LABELS[intent_code]
    if intent_code.endswith("_query") and intent_code[:-6] in CAPABILITIES:
        return f"{CAPABILITIES[intent_code[:-6]]['label']}查询"
    return intent_code


def classify(text, entities):
    """输入 + 实体 -> (意图编码, 意图名称, 能力列表, 判定理由)。"""
    lowered = str(text).lower()

    for rule in INTENT_RULES:
        if not any(keyword.lower() in lowered for keyword in rule["keywords"]):
            continue
        required_entity = rule.get("requires_entity")
        if required_entity and not entities.get(required_entity):
            continue
        return rule["code"], _label_for(rule["code"]), list(rule["capabilities"]), rule["reason"]

    # 无风险/交付关键词，但给出了订单号或「产品 + 数量」：按交付能力分析处理
    if entities.get("order_ids") or (
        entities.get("product") and entities.get("quantity")
    ):
        return (
            "order_delivery",
            _label_for("order_delivery"),
            list(DELIVERY_CAPABILITIES),
            "用户给出了具体订单实体，按交付能力分析处理",
        )

    # 只给出设备编号：按单台设备故障诊断处理
    if entities.get("equipment_ids"):
        return (
            "equipment_failure",
            _label_for("equipment_failure"),
            ["equipment_failure"],
            f"用户指向具体设备 {entities['equipment_ids'][0]}，按设备故障诊断处理",
        )

    # 只给出质量侧实体（零件 / 缺陷类型 / 批次）：按质量议题分析处理
    if entities.get("part_name") or entities.get("defect_type") or entities.get("batch"):
        return (
            "quality_issue_analysis",
            _label_for("quality_issue_analysis"),
            ["quality_issue_analysis"],
            "用户给出了质量侧实体（零件 / 缺陷类型 / 批次），按质量议题分析处理",
        )

    matched = detect_capabilities(text)
    if len(matched) == 1:
        code = f"{matched[0]}_query"
        return code, _label_for(code), matched, f"用户只关注{CAPABILITIES[matched[0]]['label']}维度"
    if len(matched) > 1:
        return (
            "mixed_query",
            _label_for("mixed_query"),
            matched,
            "用户同时关注多个维度：" + "、".join(CAPABILITIES[item]["label"] for item in matched),
        )

    return (
        "overview",
        _label_for("overview"),
        list(CAPABILITY_ORDER),
        "未识别出具体诉求，返回制造运营总览",
    )


def _action_for(capability, entities):
    if capability == "order":
        if entities.get("order_id"):
            return "analyze_order_delivery"
        if entities.get("product") and entities.get("quantity"):
            return "analyze_order_request"
        return "analyze_orders_overview"
    if capability == "equipment_failure":
        return "diagnose_equipment_failure"
    if capability == "quality_issue_analysis":
        return "analyze_quality_issue"
    return {
        "inventory": "get_inventory_summary",
        "production": "get_factory_capacity",
        "equipment": "analyze_equipment_status",
        "quality": "analyze_quality",
    }[capability]


def _reason_for(capability, entities):
    if capability == "order":
        if entities.get("order_id"):
            return f"用户关注订单 {entities['order_id']} 的交付情况，需要订单基础信息"
        if entities.get("product") and entities.get("quantity"):
            return (
                f"用户描述了订单（{entities['product']} / {entities['quantity']} 件），"
                "需要按该产品与数量测算交付能力"
            )
        return "用户需要订单整体情况，需要订单基础信息"

    if capability == "equipment_failure":
        if entities.get("equipment_id"):
            return (
                f"用户报告设备 {entities['equipment_id']} 报警/异常，"
                "需要台账状态 + 传感器读数 + 故障知识库诊断，并生成维修工单"
            )
        return "用户关注单台设备故障，需要设备故障诊断"

    if capability == "quality_issue_analysis":
        scope = []
        if entities.get("part_name") or entities.get("product"):
            scope.append(str(entities.get("part_name") or entities.get("product")))
        if entities.get("defect_type"):
            scope.append(str(entities["defect_type"]))
        if entities.get("batch"):
            scope.append(str(entities["batch"]))
        scope_text = "、".join(scope) if scope else "全部产品"
        return (
            f"用户关注质量下降/异常（{scope_text}），"
            "需要时间趋势对比、质量追溯（工序→设备→生产记录）与改善知识库建议"
        )

    return {
        "inventory": "交付能力取决于物料齐套性，需要库存与安全库存状态",
        "production": "交付能力取决于瓶颈产能，需要 MES 产线与在产产能",
        "equipment": "需要设备台账、维保与传感器数据评估设备风险",
        "quality": "需要缺陷统计与原有质量分析结果评估质量风险",
    }[capability]


def build_steps(capabilities, entities):
    """能力列表 -> 执行步骤（每步含归属 Agent、动作、理由与上下文参数）。"""
    steps = []
    for index, capability in enumerate(capabilities, start=1):
        meta = CAPABILITIES[capability]
        step = {
            "step": index,
            "capability": capability,
            "capability_label": meta["label"],
            "agent": meta["agent"],
            "tool_module": meta["tool_module"],
            "action": _action_for(capability, entities),
            "reason": _reason_for(capability, entities),
        }

        if capability in DELIVERY_CAPABILITIES:
            step_arguments = {}
            if entities.get("order_id"):
                step_arguments["order_id"] = entities["order_id"]
            if entities.get("product"):
                step_arguments["product"] = entities["product"]
            if entities.get("quantity") is not None:
                step_arguments["quantity"] = entities["quantity"]
            if entities.get("delivery_days") is not None:
                step_arguments["delivery_days"] = entities["delivery_days"]
            if step_arguments:
                step["arguments"] = step_arguments
        elif capability == "equipment_failure" and entities.get("equipment_id"):
            step["arguments"] = {"equipment_id": entities["equipment_id"]}
        elif capability == "quality_issue_analysis":
            step_arguments = {}
            for entity_key in (
                "part_name",
                "product",
                "defect_type",
                "process",
                "batch",
                "days",
            ):
                value = entities.get(entity_key)
                if value is not None:
                    step_arguments[entity_key] = value
            if step_arguments:
                step["arguments"] = step_arguments

        steps.append(step)

    return steps


def _dispatch_arguments(entities):
    """传给子 Agent 的上下文（去掉 None，保留 today 便于测试固定日期）。"""
    arguments = {}
    for key in (
        "order_ids",
        "order_id",
        "equipment_ids",
        "equipment_id",
        "product",
        "part_name",
        "defect_type",
        "process",
        "batch",
        "days",
        "quantity",
        "delivery_days",
        "deadline",
        "today",
    ):
        value = entities.get(key)
        if value is not None:
            arguments[key] = value
    return arguments


def build_plan(user_input, use_llm=None, llm_client_factory=None):
    """生成执行计划（LLM 优先，失败或未配置时回退规则）。

    参数：
        user_input:         用户输入文本。
        use_llm:            None（默认）= 有 DEEPSEEK_API_KEY 就用 LLM；True/False 强制开关。
        llm_client_factory: 可注入的 LLM 客户端工厂（测试用）。

    返回 dict：
        user_input, intent, intent_code, capabilities, entities, steps, planner, notes
    """
    text = str(user_input or "").strip()
    entities = extract_entities(text)
    intent_code, intent_label, capabilities, intent_reason = classify(text, entities)
    steps = build_steps(capabilities, entities)

    plan = {
        "user_input": text,
        "intent": intent_label,
        "intent_code": intent_code,
        "intent_reason": intent_reason,
        "capabilities": capabilities,
        "entities": entities,
        "steps": steps,
        "planner": "rule",
        "risk_focus": intent_code == "comprehensive_risk",
        "notes": [],
    }

    active_use_llm = _llm_available() if use_llm is None else bool(use_llm)
    if not active_use_llm:
        if use_llm is False:
            plan["notes"].append("已按 --no-llm 强制使用规则规划")
        return plan

    llm_result = _llm_plan(text, client_factory=llm_client_factory)
    if not llm_result or not llm_result.get("capabilities"):
        plan["notes"].append(
            "LLM 规划未采纳（未配置 DEEPSEEK_API_KEY / 依赖缺失 / 调用失败 / 未选出合法能力），"
            "已回退规则规划"
        )
        return plan

    llm_capabilities = [
        capability
        for capability in ALL_CAPABILITY_ORDER
        if capability in set(llm_result["capabilities"])
    ]

    # 规则与 LLM 取并集：LLM 只能增补，不能削减规则判定的必要能力
    merged = set(capabilities) | set(llm_capabilities)
    llm_order_ids = list(llm_result.get("order_ids") or [])
    if llm_order_ids or entities.get("order_ids"):
        merged.add("order")
        if plan["risk_focus"] or intent_code == "order_delivery":
            merged.update(DELIVERY_CAPABILITIES)

    final_capabilities = [
        capability for capability in ALL_CAPABILITY_ORDER if capability in merged
    ]
    final_entities = dict(entities)
    if llm_order_ids:
        final_entities["order_ids"] = sorted(set(entities.get("order_ids") or []) | set(llm_order_ids))
        final_entities["order_id"] = final_entities["order_ids"][0]

    plan.update(
        {
            "capabilities": final_capabilities,
            "entities": final_entities,
            "steps": build_steps(final_capabilities, final_entities),
            "planner": "rule+llm",
            "llm": {
                "requested": llm_result["capabilities"],
                "intent": llm_result.get("llm_intent"),
                "order_ids": llm_order_ids,
            },
        }
    )
    plan["notes"].append(
        "LLM 建议能力："
        + "、".join(CAPABILITIES[item]["label"] for item in llm_capabilities)
        + "；与规则能力取并集以保证关键维度不缺失"
    )
    return plan


def explain_plan(plan):
    """把执行计划转成人类可读文本（CLI 输出用）。"""
    lines = [
        f"用户输入：{plan['user_input']}",
        f"意图：{plan['intent']}（{plan['intent_code']}）—— {plan['intent_reason']}",
        f"规划方式：{plan['planner']}",
    ]

    entity_labels = {
        "order_id": "订单编号",
        "equipment_id": "设备编号",
        "product": "产品",
        "part_name": "零件",
        "defect_type": "缺陷类型",
        "process": "工序",
        "batch": "批次",
        "quantity": "数量",
        "delivery_days": "交期天数",
        "deadline": "交付日期",
    }
    entity_parts = []
    for key, label in entity_labels.items():
        value = plan["entities"].get(key)
        if value in (None, "", []):
            continue
        entity_parts.append(f"{label}={value}")
    if entity_parts:
        lines.append("识别实体：" + "、".join(entity_parts))

    lines.append("执行计划：")
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


def _llm_available():
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())


def _create_llm_client(timeout=20):
    """创建 DeepSeek 客户端；测试可替换本函数注入假客户端。"""
    from openai import OpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_DEEPSEEK_BASE_URL
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)


def _llm_plan(user_input, client_factory=None, timeout=20):
    """LLM 规划：只返回「能力选择」建议，任何失败都返回 None。

    安全约束：LLM 只能从 ``CAPABILITIES`` 注册表中选择能力；
    执行计划结构始终由本模块生成，LLM 不产出可执行步骤本身。
    """
    if not _llm_available():
        return None

    factory = client_factory or _create_llm_client
    try:
        client = factory(timeout=timeout)
        response = client.chat.completions.create(
            model=os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_DEEPSEEK_MODEL,
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

    capabilities = [str(value) for value in raw_capabilities if str(value) in CAPABILITIES]
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
# 分段风险报告
# --------------------------------------------------------------------------


def _risk_section_order(results):
    order_result = results.get("order_agent") or {}
    deliverability = order_result.get("deliverability")
    if deliverability:
        return {
            "capability": "order",
            "title": SECTION_TITLES["order"],
            "risk": deliverability["risk"],
            "reason": deliverability["reason"],
            "suggestion": deliverability["suggestion"],
            "order_source": deliverability.get("order_source"),
            "order_id": deliverability.get("order_id"),
        }
    return {
        "capability": "order",
        "title": SECTION_TITLES["order"],
        "risk": order_result.get("risk", "unknown"),
        "reason": order_result.get("reason", "无订单结果"),
        "suggestion": order_result.get("suggestion", ""),
    }


def _risk_section_inventory(results):
    material = (results.get("order_agent") or {}).get("material_summary") or {}
    shortage = int(material.get("shortage_count") or 0)
    total = int(material.get("material_count") or 0)

    if shortage:
        return {
            "capability": "inventory",
            "title": SECTION_TITLES["inventory"],
            "risk": "medium",
            "reason": (
                f"{total} 项物料中有 {shortage} 项低于安全库存："
                + "、".join(str(item) for item in material.get("shortage_materials") or [])
            ),
            "suggestion": "优先催料与备料，重点跟踪预警物料的到货时间",
        }
    return {
        "capability": "inventory",
        "title": SECTION_TITLES["inventory"],
        "risk": "low",
        "reason": f"{total} 项物料库存均在安全库存之上",
        "suggestion": "保持常规备料节奏",
    }


def _risk_section_production(results):
    order_result = results.get("order_agent") or {}
    capacity = order_result.get("capacity_summary") or {}
    deliverability = order_result.get("deliverability") or {}
    blocked_lines = [
        line for line in (deliverability.get("capacity_lines") or []) if line.get("blocked")
    ]

    total = int(capacity.get("total_daily_capacity") or 0)
    running = int(capacity.get("running_daily_capacity") or 0)
    yield_rate = capacity.get("average_yield_rate") or 0
    running_lines = int(capacity.get("running_line_count") or 0)

    if blocked_lines:
        blocked_text = "、".join(f"{line['process']}/{line['equipment']}" for line in blocked_lines)
        return {
            "capability": "production",
            "title": SECTION_TITLES["production"],
            "risk": "high",
            "reason": f"订单相关工序存在停机/故障产线：{blocked_text}，该工序有效日产能为 0",
            "suggestion": "启用替代产线或外协加工后重新排产",
        }
    if running <= 0:
        return {
            "capability": "production",
            "title": SECTION_TITLES["production"],
            "risk": "high",
            "reason": "当前没有在产产线，可用日产能为 0",
            "suggestion": "恢复产线后再排产",
        }

    risk = "medium" if running < total else "low"
    reason = (
        f"总日产能 {total} 件，在产 {running} 件（{running_lines} 条产线），"
        f"在产平均良率 {yield_rate:.1%}"
    )
    if risk == "medium":
        reason += f"；有 {total - running} 件/天产能未投入（停机/保养/待机）"

    return {
        "capability": "production",
        "title": SECTION_TITLES["production"],
        "risk": risk,
        "reason": reason,
        "suggestion": "恢复停机或保养产线以提升在产产能" if risk == "medium" else "保持当前排产",
    }


def _risk_section_agent(capability, results):
    agent_result = results.get(CAPABILITIES[capability]["agent"]) or {}
    return {
        "capability": capability,
        "title": SECTION_TITLES[capability],
        "risk": agent_result.get("risk", "unknown"),
        "reason": agent_result.get("reason", f"无{CAPABILITIES[capability]['label']}结果"),
        "suggestion": agent_result.get("suggestion", ""),
    }


def _section_builder(capability):
    return {
        "order": _risk_section_order,
        "inventory": _risk_section_inventory,
        "production": _risk_section_production,
    }.get(capability, lambda results: _risk_section_agent(capability, results))


def _max_risk(risks):
    known = [risk for risk in risks if risk in RISK_ORDER]
    if not known:
        return "unknown"
    return max(known, key=RISK_ORDER.index)


def build_risk_report(plan, results):
    """把各 Agent 结果组织成分段风险报告（总体风险 = 各段最高风险）。

    分段标题固定为：订单交付风险 / 物料库存风险 / 产能风险 / 设备风险 / 质量风险，
    因此风险类问题必然包含「质量风险」「设备风险」两段。
    """
    sections = []
    for capability in plan["capabilities"]:
        section = _section_builder(capability)(results)
        if section:
            sections.append(section)

    return {
        "overall_risk": _max_risk([section["risk"] for section in sections]),
        "sections": sections,
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

    arguments = _dispatch_arguments(plan.get("entities") or {})
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


def handle(user_input, use_llm=None, llm_client_factory=None):
    """Supervisor 主入口：生成执行计划、调度子 Agent，并汇总分段风险报告。"""
    plan = build_plan(user_input, use_llm=use_llm, llm_client_factory=llm_client_factory)
    execution = execute_plan(plan)
    return {
        "user_input": plan["user_input"],
        "intent": plan["intent"],
        "intent_code": plan["intent_code"],
        "plan": plan,
        "results": execution["results"],
        "risk_report": build_risk_report(plan, execution["results"]),
    }


def main():
    """命令行入口。

    示例：
        python -m agents.supervisor_agent "分析订单O001能否按时完成"
        python -m agents.supervisor_agent "工厂收到10000件电机壳体订单，15天交付，帮我分析风险"
        python -m agents.supervisor_agent --plan-only --no-llm "设备有没有故障"
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Supervisor Agent：生成执行计划并调度子 Agent"
    )
    parser.add_argument("query", nargs="*", help="用户输入，例如：分析订单O001能否按时完成")
    parser.add_argument("--llm", action="store_true", help="强制启用 LLM 辅助规划")
    parser.add_argument("--no-llm", action="store_true", help="强制使用规则规划（不调用 LLM）")
    parser.add_argument("--plan-only", action="store_true", help="只输出执行计划，不执行子 Agent")
    args = parser.parse_args()

    user_input = " ".join(args.query).strip() or "分析订单O001能否按时完成"
    use_llm = False if args.no_llm else (True if args.llm else None)

    plan = build_plan(user_input, use_llm=use_llm)

    print(explain_plan(plan))
    print()

    if args.plan_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    execution = execute_plan(plan)
    report = build_risk_report(plan, execution["results"])
    print(json.dumps({"results": execution["results"], "risk_report": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
