"""生产计划规则引擎（S5-A-03）。

第一版**不做优化算法**，只按固定规则排产：

1. **优先满足交期**：按流水（相邻工序允许重叠）估算工期，超出交期即给出压缩方案；
2. **避开故障设备**：停机/故障产线不进计划，优先替换为同工序的可用设备；
3. **优先高风险订单**：高优先级订单按加急采购与优先排产处理；
4. **考虑库存**：按 BOM 计算本单物料需求，缺料时在计划最前面插入采购备料阶段。

工期模型（v1，简单可解释）：

    工序 i 的加工天数 d_i = ceil(数量 / 有效日产能_i)
    有效日产能：产线停机（stopped）或设备故障（fault）记为 0，否则取 daily_capacity
    流水重叠：工序 i 从第 (i-1)×流转天数 天开始（流转天数默认 1 天，可配置）
    生产工期 = max_i(流转偏移_i + d_i)          <- 瓶颈工序决定整体节奏
    总工期   = 采购备料天数 + 生产工期
    串行工期 = 采购备料天数 + Σ d_i             <- 工序完全不重叠的上限参照

交付判定：``总工期 <= 交期剩余天数`` 视为可满足；否则按
「替代设备 → 加急采购 → 增加班次 → 协商交期」的顺序给出可执行的压缩建议，
并对每一步给出模拟后的工期。
"""

import math

import pandas as pd


# 采购备料（缺料时插入计划最前面）
PURCHASE_LEAD_DAYS = 3
PURCHASE_LEAD_DAYS_EXPRESS = 1

# 工序间流转（流水重叠）天数
TRANSFER_DAYS = 1

# 增加班次可提升的产能比例
SHIFT_BOOST_RATIO = 0.3

DERATED_PRODUCTION_STATUSES = ("maintenance", "idle")
DERATED_EQUIPMENT_STATUSES = ("warning",)

RISK_ORDER = ["low", "medium", "high"]

# 有效产能明细字段（与 agents/order_agent 的输出契约保持一致）
CAPACITY_DETAIL_COLUMNS = [
    "process",
    "equipment",
    "status",
    "equipment_status",
    "daily_capacity",
    "effective_capacity",
    "blocked",
    "derated",
]


def _native(value):
    """把 numpy 标量转成原生类型，保证结果可 JSON 序列化。"""
    return value.item() if hasattr(value, "item") else value


def _records(frame):
    """DataFrame -> 原生类型记录列表。"""
    return [
        {key: _native(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _to_int(value):
    number = pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0).iloc[0]
    return int(number)


def _as_day(value):
    if value is None or value == "":
        return None
    stamp = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(stamp) else stamp.normalize()


# --------------------------------------------------------------------------
# 产能模型（order_agent 与排产工具共用同一实现）
# --------------------------------------------------------------------------


def evaluate_effective_capacity(lines, equipment_status=None):
    """按工序计算有效日产能，返回瓶颈产能与受阻/降额工序。

    参数：
        lines: 产线数据（DataFrame 或记录列表），字段
               ``process`` / ``equipment`` / ``daily_capacity`` / ``status``。
        equipment_status: ``{设备编号: 设备状态}``（来自设备台账）。

    返回：
        ``{"source", "bottleneck", "lines", "blocked_lines", "derated_lines"}``
        —— 产线为空时 ``bottleneck`` 为 ``None``，由调用方决定回退口径。
    """
    frame = lines if isinstance(lines, pd.DataFrame) else pd.DataFrame(list(lines or []))
    if frame.empty:
        return {
            "source": "factory_running_capacity",
            "bottleneck": None,
            "lines": [],
            "blocked_lines": [],
            "derated_lines": [],
        }

    statuses = {
        str(key): str(value).strip().lower() for key, value in (equipment_status or {}).items()
    }

    evaluated = frame.copy()
    evaluated["effective_capacity"] = (
        pd.to_numeric(evaluated["daily_capacity"], errors="coerce").fillna(0).astype("int64")
    )
    production_status = evaluated["status"].astype(str).str.lower()
    evaluated["equipment_status"] = (
        evaluated["equipment"].astype(str).map(lambda value: statuses.get(value, "unknown"))
    )
    equipment_state = evaluated["equipment_status"]

    blocked_mask = (production_status == "stopped") | (equipment_state == "fault")
    derated_mask = (
        production_status.isin(DERATED_PRODUCTION_STATUSES)
        | equipment_state.isin(DERATED_EQUIPMENT_STATUSES)
    ) & (~blocked_mask)

    evaluated.loc[blocked_mask, "effective_capacity"] = 0
    evaluated["blocked"] = blocked_mask
    evaluated["derated"] = derated_mask

    line_details = _records(evaluated[CAPACITY_DETAIL_COLUMNS])

    return {
        "source": "product_process_bottleneck",
        "bottleneck": int(evaluated["effective_capacity"].min()),
        "lines": line_details,
        "blocked_lines": [item for item in line_details if item["blocked"]],
        "derated_lines": [item for item in line_details if item["derated"]],
    }


# --------------------------------------------------------------------------
# 排产
# --------------------------------------------------------------------------


def build_stages(capacity, alternatives=None):
    """把本产品工序链整理为排产工序（含替代设备与可用性）。

    规则 2「避开故障设备」：本工序产线受阻且存在可用替代设备时，
    计划会自动改用替代设备，并在该工序上留下替换说明。
    """
    lines = (capacity or {}).get("lines") or []
    alternatives = alternatives or {}

    stages = []
    for index, line in enumerate(lines):
        process = str(line["process"])
        equipment = str(line["equipment"])
        candidates = [
            {
                "equipment": str(item["equipment"]),
                "daily_capacity": _to_int(item.get("daily_capacity")),
                "blocked": bool(item.get("blocked")),
                "status": str(item.get("status", "")),
            }
            for item in alternatives.get(process, [])
        ]

        # 同一台设备可能出现在多条产品线上，按设备去重（保留最大日产能）
        deduped = {}
        for item in candidates:
            current = deduped.get(item["equipment"])
            if current is None or item["daily_capacity"] > current["daily_capacity"]:
                deduped[item["equipment"]] = item
        candidates = list(deduped.values())

        usable = [
            item for item in candidates if not item["blocked"] and item["equipment"] != equipment
        ]

        selected_equipment = equipment
        selected_capacity = _to_int(line.get("effective_capacity"))
        note = None

        if bool(line.get("blocked")):
            if usable:
                substitute = max(usable, key=lambda item: item["daily_capacity"])
                selected_equipment = substitute["equipment"]
                selected_capacity = substitute["daily_capacity"]
                note = (
                    f"原设备 {equipment} 停机或故障，改用替代设备 {substitute['equipment']}"
                    f"（{substitute['daily_capacity']} 件/天）"
                )
            else:
                selected_capacity = 0
                note = f"原设备 {equipment} 停机或故障，且无可用替代设备"

        stages.append(
            {
                "index": index,
                "process": process,
                "equipment": selected_equipment,
                "original_equipment": equipment,
                "daily_capacity": _to_int(line.get("daily_capacity")),
                "effective_capacity": selected_capacity,
                "blocked": bool(line.get("blocked")),
                "derated": bool(line.get("derated")),
                "substituted": selected_equipment != equipment,
                "alternatives": candidates,
                "usable_alternatives": usable,
                "note": note,
            }
        )

    return stages


def simulate_makespan(stages, quantity, extra_capacity=None, transfer_days=TRANSFER_DAYS):
    """模拟生产工期（不含采购备料）；存在无法开工的工序时返回 None。"""
    extra_capacity = extra_capacity or {}

    makespan = 0
    for stage in stages:
        capacity = _to_int(stage.get("effective_capacity")) + _to_int(
            extra_capacity.get(stage["process"], 0)
        )
        if capacity <= 0:
            return None
        offset = stage["index"] * transfer_days
        makespan = max(makespan, offset + math.ceil(quantity / capacity))

    return makespan or None


def _day_label(start_day, days):
    if days is None or days <= 0:
        return None
    end_day = start_day + days - 1
    return f"Day{start_day}" if days == 1 else f"Day{start_day}-{end_day}"


def build_schedule(stages, quantity, material_segments=None, transfer_days=TRANSFER_DAYS):
    """生成日级排产明细（含采购备料阶段与各工序日期区间）。"""
    schedule = []
    seq = 1

    day_cursor = 1
    for segment in material_segments or []:
        days = _to_int(segment.get("days"))
        schedule.append(
            {
                "seq": seq,
                "activity": segment["activity"],
                "type": "material",
                "process": None,
                "equipment": None,
                "daily_capacity": None,
                "days": days,
                "start_day": day_cursor,
                "end_day": day_cursor + days - 1,
                "day_label": _day_label(day_cursor, days),
                "note": segment.get("note"),
            }
        )
        day_cursor += days
        seq += 1

    production_start = day_cursor
    for stage in stages:
        capacity = _to_int(stage["effective_capacity"])
        days = math.ceil(quantity / capacity) if capacity > 0 else None
        offset = stage["index"] * transfer_days
        start_day = production_start + offset if days else None
        end_day = start_day + days - 1 if days else None

        schedule.append(
            {
                "seq": seq,
                "activity": stage["process"],
                "type": "process",
                "process": stage["process"],
                "equipment": stage["equipment"],
                "daily_capacity": capacity,
                "days": days,
                "start_day": start_day,
                "end_day": end_day,
                "day_label": _day_label(start_day, days) if days else None,
                "note": stage.get("note"),
            }
        )
        seq += 1

    return schedule


def format_plan_lines(schedule):
    """排产明细 -> 「Day1-3：采购备料 ...」形式的人类可读文本。"""
    lines = []
    for item in schedule:
        if not item["day_label"]:
            lines.append(f"{item['activity']}：无法排产（{item['note'] or '产能为 0'}）")
            continue

        if item["type"] == "material":
            detail = item["note"] or "物料准备"
            lines.append(f"{item['day_label']}：{item['activity']}（{detail}）")
        else:
            detail = f"{item['equipment']}，{item['daily_capacity']} 件/天，需 {item['days']} 天"
            if item.get("note"):
                detail += f"；{item['note']}"
            lines.append(f"{item['day_label']}：{item['activity']}（{detail}）")

    return lines


# --------------------------------------------------------------------------
# 风险与建议
# --------------------------------------------------------------------------


def _material_phase(material_requirements, purchase_days, express):
    """缺料时生成采购备料阶段。"""
    shortages = [
        item for item in (material_requirements or []) if _to_int(item.get("shortage")) > 0
    ]
    if not shortages:
        return [], {
            "requirements": list(material_requirements or []),
            "shortage_materials": [],
            "purchase_days": 0,
            "express": express,
        }

    for item in shortages:
        item["lead_days"] = purchase_days

    names = "、".join(str(item["material"]) for item in shortages)
    detail = "、".join(
        f"{item['material']}缺口 {_to_int(item['shortage'])}{item.get('unit', '')}"
        for item in shortages
    )

    segments = [
        {
            "activity": f"采购备料（{names}）",
            "days": purchase_days,
            "note": f"{detail}；{'加急采购' if express else '常规采购'} {purchase_days} 天",
        }
    ]

    return segments, {
        "requirements": list(material_requirements or []),
        "shortage_materials": [str(item["material"]) for item in shortages],
        "purchase_days": purchase_days,
        "express": express,
    }


def build_risks(schedule, stages, timeline, material, quality_risk=None):
    """汇总计划风险。"""
    risks = []

    if not stages:
        risks.append(
            {
                "level": "high",
                "item": "该产品在 MES 中没有对应产线",
                "impact": "无法排产，需要先确认产品与产线（工序/设备）映射",
            }
        )
        return risks

    for stage in stages:
        if not stage["blocked"]:
            continue
        if stage["substituted"]:
            risks.append(
                {
                    "level": "medium",
                    "item": (
                        f"{stage['process']} 工序原设备 {stage['original_equipment']} 停机或故障"
                    ),
                    "impact": (
                        f"已改用替代设备 {stage['equipment']}"
                        f"（{stage['effective_capacity']} 件/天），需确认其现有负荷"
                    ),
                }
            )
        else:
            risks.append(
                {
                    "level": "high",
                    "item": (
                        f"{stage['process']} 工序的 {stage['original_equipment']} 停机或故障"
                    ),
                    "impact": "无可用替代设备，该工序无法开工，需外协或抢修",
                }
            )

    for stage in stages:
        for candidate in stage["alternatives"]:
            if not candidate["blocked"] or candidate["equipment"] == stage["original_equipment"]:
                continue
            risks.append(
                {
                    "level": "medium",
                    "item": (
                        f"{stage['process']} 工序备用设备 {candidate['equipment']} 停机或故障"
                    ),
                    "impact": f"扩产时不可用（日产能 {candidate['daily_capacity']} 件）",
                }
            )

    if material["shortage_materials"]:
        for item in material["requirements"]:
            if _to_int(item.get("shortage")) <= 0:
                continue
            risks.append(
                {
                    "level": "high",
                    "item": f"{item['material']} 缺口 {_to_int(item['shortage'])}{item.get('unit', '')}",
                    "impact": "开工前必须到料，否则计划整体顺延",
                }
            )

    if timeline["available_days"] is not None:
        made = timeline["total_days"]
        if made is not None and made > timeline["available_days"]:
            risks.append(
                {
                    "level": "high",
                    "item": (
                        f"计划工期 {made} 天 > 交期剩余 {timeline['available_days']} 天"
                    ),
                    "impact": f"超出 {made - timeline['available_days']} 天，无法满足交期",
                }
            )
        elif made is not None and made > timeline["available_days"] * 0.8:
            risks.append(
                {
                    "level": "medium",
                    "item": f"计划工期 {made} 天接近交期剩余 {timeline['available_days']} 天",
                    "impact": "缓冲不足，任一异常都可能造成延期",
                }
            )

    candidates = [stage for stage in stages if stage["effective_capacity"] > 0]
    if candidates:
        bottleneck_stage = min(candidates, key=lambda stage: stage["effective_capacity"])
        risks.append(
            {
                "level": "info",
                "item": (
                    f"瓶颈工序：{bottleneck_stage['process']}"
                    f"（{bottleneck_stage['equipment']}，{bottleneck_stage['effective_capacity']} 件/天）"
                ),
                "impact": "决定整体产出节奏",
            }
        )

    if quality_risk:
        risks.append(
            {
                "level": str(quality_risk.get("risk", "medium")),
                "item": "在制质量风险",
                "impact": str(quality_risk.get("reason", "")),
            }
        )

    return risks


def build_suggestions(stages, quantity, timeline, material, priority):
    """按「替代设备 → 加急采购 → 增加班次 → 协商交期」给出建议，并模拟效果。"""
    suggestions = []
    feasible_now = bool(timeline["feasible"])

    if not stages:
        return ["确认该产品在 data/production.csv 中的工序与设备后再排产"]

    bottleneck = None
    candidates = [stage for stage in stages if stage["effective_capacity"] > 0]
    if candidates:
        bottleneck = min(candidates, key=lambda stage: stage["effective_capacity"])

    # 1）替代设备 / 并行设备
    extra_capacity = {}
    if bottleneck is not None:
        usable = bottleneck["usable_alternatives"]
        if usable and (not feasible_now or bottleneck["effective_capacity"] <= quantity):
            extra = sum(item["daily_capacity"] for item in usable)
            extra_capacity[bottleneck["process"]] = extra
            simulated = simulate_makespan(stages, quantity, extra_capacity)
            effect = (
                f"，启用后生产工期 {simulated} 天"
                if simulated is not None
                else ""
            )
            names = "、".join(
                f"{item['equipment']}（{item['daily_capacity']} 件/天）" for item in usable
            )
            suggestions.append(
                f"启用 {bottleneck['process']} 的替代/并行设备：{names}，"
                f"瓶颈产能 {bottleneck['effective_capacity']} → "
                f"{bottleneck['effective_capacity'] + extra} 件/天{effect}"
            )

    # 2）采购加急
    if material["shortage_materials"] and not material["express"]:
        accelerated = dict(extra_capacity)
        simulated = simulate_makespan(stages, quantity, accelerated)
        saved = PURCHASE_LEAD_DAYS - PURCHASE_LEAD_DAYS_EXPRESS
        suggestions.append(
            f"将采购改为加急（{PURCHASE_LEAD_DAYS} 天 → {PURCHASE_LEAD_DAYS_EXPRESS} 天，"
            f"可省 {saved} 天）："
            + "、".join(material["shortage_materials"])
        )

    # 3）增加班次
    shift_extra = {
        stage["process"]: int(stage["effective_capacity"] * SHIFT_BOOST_RATIO)
        for stage in stages
        if stage["effective_capacity"] > 0
    }
    if shift_extra and not feasible_now:
        combined = dict(extra_capacity)
        for process, value in shift_extra.items():
            combined[process] = combined.get(process, 0) + value
        simulated = simulate_makespan(stages, quantity, combined)
        effect = f"（生产工期可降至 {simulated} 天）" if simulated is not None else ""
        suggestions.append(
            f"关键工序增加班次，产能约提升 {int(SHIFT_BOOST_RATIO * 100)}%{effect}"
        )

    # 4）交期/批次
    if timeline["available_days"] is not None and not feasible_now:
        best_extra = dict(extra_capacity)
        for process, value in shift_extra.items():
            best_extra[process] = best_extra.get(process, 0) + value
        best_production = simulate_makespan(stages, quantity, best_extra)
        best_total = (
            best_production + material["purchase_days"] if best_production is not None else None
        )
        if best_total is not None and best_total <= timeline["available_days"]:
            suggestions.append(
                f"按上述措施执行后总工期 {best_total} 天，可满足交期 "
                f"{timeline['available_days']} 天"
            )
        else:
            gap = (
                timeline["total_days"] - timeline["available_days"]
                if timeline["total_days"] is not None
                else None
            )
            suggestions.append(
                "与客户协商交期或拆分批次交付"
                + (f"（当前计划超出 {gap} 天）" if gap and gap > 0 else "")
            )
    elif feasible_now:
        suggestions.append(
            f"当前计划 {timeline['total_days']} 天满足交期 {timeline['available_days']} 天，按计划执行"
        )

    if str(priority).lower() == "high":
        suggestions.append("高优先级订单：优先排产并预留异常缓冲时间")

    return suggestions


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------


def build_production_plan(
    product,
    quantity,
    deadline=None,
    today=None,
    priority="normal",
    capacity=None,
    alternatives=None,
    material_requirements=None,
    quality_risk=None,
):
    """生成生产计划（规则驱动，第一版不做优化算法）。

    参数：
        product:      产品名称（MES 产品）。
        quantity:     订单数量。
        deadline:     交付日期（ISO 字符串 / 日期对象 / None）。
        today:        参考日期，缺省系统当天。
        priority:     订单优先级（high / normal / low）。
        capacity:     ``evaluate_effective_capacity()`` 的结果（本产品工序链）。
        alternatives: ``{工序: [{equipment, daily_capacity, blocked, status}]}``。
        material_requirements: ``[{material, required, stock, safety_stock, shortage, unit}]``。
        quality_risk: 可选，``{"risk": ..., "reason": ...}``（来自质量 Agent）。

    返回 dict：product / quantity / deadline / timeline / material / capacity /
    schedule / plan_lines / risks / suggestions / status。
    """
    quantity = max(int(quantity or 0), 0)
    reference = _as_day(today)
    deadline_day = _as_day(deadline)
    available_days = (
        None if deadline_day is None else int((deadline_day - reference).days)
    )

    priority_key = str(priority or "normal").strip().lower()
    express = priority_key == "high"
    purchase_days = PURCHASE_LEAD_DAYS_EXPRESS if express else PURCHASE_LEAD_DAYS

    stages = build_stages(capacity, alternatives)
    material_segments, material = _material_phase(
        material_requirements, purchase_days, express
    )

    production_days = simulate_makespan(stages, quantity)
    serial_days = (
        sum(
            math.ceil(quantity / stage["effective_capacity"])
            for stage in stages
            if stage["effective_capacity"] > 0
        )
        if stages and all(stage["effective_capacity"] > 0 for stage in stages)
        else None
    )

    total_days = (
        None if production_days is None else production_days + material["purchase_days"]
    )

    timeline = {
        "today": None if reference is None else reference.date().isoformat(),
        "deadline": None if deadline_day is None else deadline_day.date().isoformat(),
        "available_days": available_days,
        "material_days": material["purchase_days"],
        "production_days": production_days,
        "serial_days": serial_days,
        "total_days": total_days,
        "feasible": bool(
            total_days is not None
            and available_days is not None
            and total_days <= available_days
        ),
        "gap_days": (
            None
            if total_days is None or available_days is None
            else total_days - available_days
        ),
    }

    schedule = build_schedule(stages, quantity, material_segments)
    risks = build_risks(schedule, stages, timeline, material, quality_risk)
    suggestions = build_suggestions(stages, quantity, timeline, material, priority_key)

    if production_days is None:
        status = "blocked"
    elif timeline["feasible"]:
        status = "ok"
    else:
        status = "tight"

    return {
        "product": str(product),
        "quantity": quantity,
        "priority": priority_key,
        "deadline": timeline["deadline"],
        "timeline": timeline,
        "material": material,
        "capacity": {
            "source": (capacity or {}).get("source"),
            "bottleneck": (capacity or {}).get("bottleneck"),
            "stages": stages,
        },
        "schedule": schedule,
        "plan_lines": format_plan_lines(schedule),
        "risks": risks,
        "suggestions": suggestions,
        "status": status,
    }


def max_risk(risks):
    """取风险列表中最严重的等级（high > medium > low；info 不参与）。"""
    levels = [str(item.get("level")) for item in risks or []]
    known = [level for level in levels if level in RISK_ORDER]
    if not known:
        return "low"
    return max(known, key=RISK_ORDER.index)
