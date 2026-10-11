"""Equipment Agent：设备异常检测 + 故障诊断 + 维修工单（S3-A-02）。

两条能力：

1. ``equipment``          车队级设备健康总览（异常检测 / 维保 / 传感器告警）；
2. ``equipment_failure``  单台设备故障诊断：台账状态 + 传感器读数 + 知识库案例检索 + 维修工单。

调用链（全部经 agent_tools）：

- ``agent_tools.equipment_tools.get_equipment_records()``   -> ``tools/equipment_tool.py``
- ``agent_tools.equipment_tools.get_latest_sensor_reading()`` -> ``tools/iot_sensor_tool.py``
- ``agent_tools.equipment_tools.get_equipment_production_status()`` -> ``tools/production_tool.py``
- ``agent_tools.equipment_tools.search_fault_knowledge()``  -> ``modules/equipment_knowledge.py``（knowledge/equipment/）
- ``agent_tools.work_order_tools.create_work_order()``      -> ``data/work_orders.csv``

诊断输出（S3-A-02 约定字段，``diagnose_equipment()`` 直接返回）：

    {
      "equipment": "CNC02",
      "status": "abnormal",
      "fault": "主轴轴承异常",
      "confidence": 0.82,
      "recommendation": ["检查润滑", "检测轴承间隙"]
    }

另含 ``possible_causes`` / ``evidence`` / ``matched_cases`` / ``work_order`` 等诊断依据。
``run()`` 在多 Agent 场景下保持统一信封（``status`` 为执行状态），
诊断结果原样放在 ``diagnosis`` 字段中，并同时把 ``fault`` / ``confidence`` /
``recommendation`` / ``equipment`` 提升到顶层，便于直接读取。
"""

from agent_tools import equipment_tools, work_order_tools
from modules.equipment_analysis import DEFAULT_MAINTENANCE_INTERVAL_DAYS


ABNORMAL_SENSOR_STATUSES = ("warning", "alarm")
ABNORMAL_EQUIPMENT_STATUSES = ("warning", "fault")
ABNORMAL_PRODUCTION_STATUSES = ("stopped", "maintenance")
HIGH_CONFIDENCE = 0.8


def analyze_equipment_status(today=None):
    """车队级设备健康分析：返回结构化的 risk / reason / suggestion 与明细。"""
    summary = equipment_tools.get_equipment_summary(today=today)
    abnormal = equipment_tools.get_abnormal_list()
    maintenance_due = equipment_tools.get_maintenance_due_list(today=today)
    sensor_summary = equipment_tools.get_sensor_summary()
    sensor_alarms = equipment_tools.get_sensor_alarm_records()

    fault_ids = [item["equipment_id"] for item in abnormal if str(item["status"]).lower() == "fault"]
    warning_ids = [
        item["equipment_id"] for item in abnormal if str(item["status"]).lower() == "warning"
    ]

    reason_parts = [
        f"设备 {summary['total_equipment']} 台，正常 {summary['normal_count']} 台，"
        f"异常 {summary['abnormal_count']} 台"
        f"（预警 {summary['warning_count']}、故障 {summary['fault_count']}）"
    ]

    if fault_ids:
        risk = "high"
        reason_parts.append(
            f"故障设备：{'、'.join(fault_ids)}，相关工序产能为 0，直接影响交付"
        )
        suggestion = "立即安排抢修或启用替代设备，并同步调整排产"
    elif warning_ids:
        risk = "medium"
        reason_parts.append(f"预警设备：{'、'.join(warning_ids)}，实际产能可能下降")
        suggestion = "安排预防性维护，重点跟踪预警设备的温度与振动趋势"
    else:
        risk = "low"
        suggestion = "保持日常点检即可"

    if maintenance_due:
        due_ids = [item["equipment_id"] for item in maintenance_due]
        reason_parts.append(
            f"{len(maintenance_due)} 台设备超过 {DEFAULT_MAINTENANCE_INTERVAL_DAYS} 天未保养"
            f"（{'、'.join(due_ids)}）"
        )
        if risk == "low":
            risk = "medium"
        suggestion = "优先安排维保超期设备保养后再排产"

    if sensor_summary["alarm_count"]:
        reason_parts.append(
            f"传感器告警 {sensor_summary['alarm_count']} 条，涉及设备 "
            f"{'、'.join(sensor_summary['alarm_equipment'])}"
        )
        if risk == "low":
            risk = "medium"

    return {
        "agent": "equipment_agent",
        "status": "ok",
        "risk": risk,
        "reason": "；".join(reason_parts),
        "suggestion": suggestion,
        "equipment_summary": summary,
        "abnormal_equipment": abnormal,
        "maintenance_due": maintenance_due,
        "sensor_summary": sensor_summary,
        "sensor_alarms": sensor_alarms,
    }


# --------------------------------------------------------------------------
# 单台设备异常检测 + 故障诊断
# --------------------------------------------------------------------------


def build_observation(equipment_id, observation=None):
    """组装诊断输入：设备台账状态 + 最新传感器读数 + MES 产线状态 + 现场补充观测。

    现场补充观测（``observation``）优先于自动取数，便于「只有报警文本」的场景。
    """
    observation = dict(observation or {})

    records = equipment_tools.get_equipment_records(equipment_id=equipment_id)
    equipment = records[0] if records else {}

    latest = equipment_tools.get_latest_sensor_reading(equipment_id=equipment_id) or {}
    lines = equipment_tools.get_equipment_production_status(equipment_id)
    production_status = str(lines[0]["status"]) if lines else ""

    observed = {
        "equipment_id": str(equipment_id),
        "equipment_type": str(equipment.get("equipment_type", "")),
        "equipment_status": str(equipment.get("status", "")),
        "production_status": production_status,
        "sensor_status": str(latest.get("status", "")),
        "温度": latest.get("temperature"),
        "振动": latest.get("vibration"),
        "电流": latest.get("current"),
        "text": str(observation.get("text", "")),
        "alarm": False,
    }

    if observed["sensor_status"] in ABNORMAL_SENSOR_STATUSES:
        observed["alarm"] = True
    if observed["equipment_status"] in ABNORMAL_EQUIPMENT_STATUSES:
        observed["alarm"] = True

    for key in (
        "equipment_type",
        "equipment_status",
        "production_status",
        "sensor_status",
        "温度",
        "振动",
        "电流",
        "text",
        "alarm",
    ):
        if key in observation and observation[key] is not None:
            observed[key] = observation[key]

    if str(observed.get("sensor_status", "")) in ABNORMAL_SENSOR_STATUSES:
        observed["alarm"] = True

    return observed


def _device_status(observed):
    """设备状态判定：abnormal / normal / unknown。"""
    equipment_status = str(observed.get("equipment_status", "")).lower()
    has_data = bool(equipment_status) or bool(observed.get("sensor_status"))

    abnormal = (
        equipment_status in ABNORMAL_EQUIPMENT_STATUSES
        or str(observed.get("sensor_status", "")).lower() in ABNORMAL_SENSOR_STATUSES
        or str(observed.get("production_status", "")).lower() in ABNORMAL_PRODUCTION_STATUSES
        or bool(observed.get("alarm"))
    )

    if abnormal:
        return "abnormal"
    if equipment_status == "normal" or has_data:
        return "normal"
    return "unknown"


def _evidence(observed, top_match):
    """诊断依据文本列表。"""
    lines = []

    if observed.get("equipment_status"):
        lines.append(f"设备台账状态：{observed['equipment_status']}")
    if observed.get("production_status"):
        lines.append(f"产线状态：{observed['production_status']}")
    if observed.get("sensor_status"):
        lines.append(f"最新传感器状态：{observed['sensor_status']}")

    for key in ("温度", "振动", "电流"):
        if observed.get(key) is not None:
            lines.append(f"{key}={observed[key]}")

    if top_match:
        lines.extend(top_match.get("命中依据", []))

    if observed.get("text"):
        lines.append(f"报警文本：{observed['text']}")

    return lines


def _diagnosis_verdict(observed, status, fault, confidence):
    """诊断结论 -> Agent 统一契约的 risk / reason / suggestion。"""
    equipment_id = observed.get("equipment_id")
    equipment_status = observed.get("equipment_status") or "未知"
    sensor_status = observed.get("sensor_status") or "未知"

    if status == "abnormal":
        risk = "high" if (
            str(equipment_status).lower() == "fault" or confidence >= HIGH_CONFIDENCE
        ) else "medium"
        fault_text = f"匹配故障「{fault}」（置信度 {confidence:.2f}）" if fault else "未匹配到已知故障案例"
        reason = (
            f"设备 {equipment_id} 状态异常（台账 {equipment_status}、传感器 {sensor_status}）；"
            f"{fault_text}"
        )
        suggestion = "按诊断建议处理并生成维修工单，处理后复测传感器趋势" if fault else (
            "补充现场观测数据（温度/振动/电流/报警文本）后重新诊断"
        )
    elif status == "normal":
        risk = "low"
        reason = f"设备 {equipment_id} 状态正常（台账 {equipment_status}、传感器 {sensor_status}）"
        suggestion = "保持常规点检"
    else:
        risk = "medium"
        reason = f"设备 {equipment_id} 无台账与传感器数据，无法判定状态"
        suggestion = "核对设备编号，或按现场报警文本补充观测数据"

    return risk, reason, suggestion


def diagnose_equipment(
    equipment_id,
    observation=None,
    create_work_order=False,
    work_order_path=None,
    created_at=None,
):
    """单台设备故障诊断（S3-A-02）。

    返回 dict：
        equipment       设备编号
        status          设备状态（normal / abnormal / unknown）
        fault           匹配到的故障名称（无匹配为 None）
        confidence      知识库相似度（0~1）
        recommendation  建议处理步骤列表
        risk / reason / suggestion   Agent 统一契约结论
        possible_causes / evidence / matched_cases / observation / work_order
    """
    observed = build_observation(equipment_id, observation)
    status = _device_status(observed)

    matches = equipment_tools.search_fault_knowledge(observed, limit=3)
    top_match = matches[0] if matches else None

    if top_match:
        fault = str(top_match["标题"])
        confidence = float(top_match["confidence"])
        recommendation = list(top_match.get("处理") or [])
        possible_causes = list(top_match.get("可能原因") or [])
    else:
        fault = None
        confidence = 0.0
        possible_causes = []
        recommendation = (
            ["设备运行参数正常，保持常规点检"]
            if status == "normal"
            else ["补充现场观测数据（温度/振动/电流/报警文本）后重新诊断", "按点检标准人工确认故障现象"]
        )

    risk, reason, suggestion = _diagnosis_verdict(observed, status, fault, confidence)

    work_order = None
    if status == "abnormal":
        work_order = work_order_tools.create_work_order(
            equipment=observed["equipment_id"],
            fault=fault or "未匹配到已知故障案例",
            equipment_status=str(observed.get("equipment_status", "")),
            equipment_type=str(observed.get("equipment_type", "")),
            confidence=confidence,
            evidence="；".join(_evidence(observed, top_match)[:3]),
            source="equipment_agent",
            persist=bool(create_work_order),
            path=work_order_path,
            created_at=created_at,
        )

    return {
        "equipment": str(equipment_id),
        "status": status,
        "fault": fault,
        "confidence": round(confidence, 2),
        "recommendation": recommendation,
        "risk": risk,
        "reason": reason,
        "suggestion": suggestion,
        "possible_causes": possible_causes,
        "evidence": _evidence(observed, top_match),
        "matched_cases": matches,
        "observation": observed,
        "knowledge_base_size": equipment_tools.get_fault_knowledge_count(),
        "work_order": work_order,
    }


# --------------------------------------------------------------------------
# Agent 统一入口
# --------------------------------------------------------------------------


def run(capabilities=None, arguments=None):
    """Agent 统一入口。

    capabilities：
        equipment          车队级设备健康总览；
        equipment_failure  单台设备故障诊断（需要 ``equipment_id``）。
    """
    capabilities = list(capabilities or ["equipment"])
    arguments = dict(arguments or {})

    if "equipment_failure" in capabilities:
        equipment_id = arguments.get("equipment_id")
        if equipment_id is None:
            ids = arguments.get("equipment_ids") or []
            equipment_id = ids[0] if ids else None

        if equipment_id is None:
            return {
                "agent": "equipment_agent",
                "status": "ok",
                "capabilities": capabilities,
                "equipment": None,
                "device_status": "unknown",
                "fault": None,
                "confidence": 0.0,
                "recommendation": [],
                "risk": "medium",
                "reason": "未提供设备编号，无法进行单台设备故障诊断",
                "suggestion": "请提供设备编号（如 CNC02）后重新诊断",
                "diagnosis": None,
            }

        diagnosis = diagnose_equipment(
            equipment_id,
            observation=arguments.get("observation"),
            create_work_order=bool(arguments.get("create_work_order")),
            work_order_path=arguments.get("work_order_path"),
            created_at=arguments.get("created_at"),
        )

        result = {
            "agent": "equipment_agent",
            "status": "ok",
            "capabilities": capabilities,
            "equipment": diagnosis["equipment"],
            "device_status": diagnosis["status"],
            "fault": diagnosis["fault"],
            "confidence": diagnosis["confidence"],
            "recommendation": diagnosis["recommendation"],
            "risk": diagnosis["risk"],
            "reason": diagnosis["reason"],
            "suggestion": diagnosis["suggestion"],
            "diagnosis": diagnosis,
        }

        if "equipment" in capabilities:
            fleet = analyze_equipment_status(today=arguments.get("today"))
            for key in (
                "equipment_summary",
                "abnormal_equipment",
                "maintenance_due",
                "sensor_summary",
                "sensor_alarms",
            ):
                result[key] = fleet[key]

        return result

    result = analyze_equipment_status(today=arguments.get("today"))
    result["capabilities"] = capabilities
    return result


def main():
    """命令行入口。

    示例：
        python -m agents.equipment_agent                       # 车队设备健康总览
        python -m agents.equipment_agent CNC02                 # 单台设备故障诊断
        python -m agents.equipment_agent CNC02 --work-order    # 诊断并落库维修工单
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Equipment Agent 设备健康与故障诊断")
    parser.add_argument("equipment_id", nargs="?", help="设备编号，如 CNC02；缺省输出车队总览")
    parser.add_argument("--work-order", action="store_true", help="生成并落库维修工单")
    parser.add_argument("--temperature", type=float, help="现场观测：温度 ℃")
    parser.add_argument("--vibration", type=float, help="现场观测：振动 mm/s")
    parser.add_argument("--current", type=float, help="现场观测：电流 A")
    parser.add_argument("--alarm-text", help="现场报警文本")
    args = parser.parse_args()

    if not args.equipment_id:
        print(json.dumps(run(capabilities=["equipment"]), ensure_ascii=False, indent=2))
        return

    observation = {
        key: value
        for key, value in (
            ("温度", args.temperature),
            ("振动", args.vibration),
            ("电流", args.current),
            ("text", args.alarm_text),
        )
        if value is not None
    }

    payload = diagnose_equipment(
        args.equipment_id,
        observation=observation,
        create_work_order=args.work_order,
    )

    ordered = {
        key: payload[key]
        for key in ("equipment", "status", "fault", "confidence", "recommendation")
    }
    ordered.update({key: value for key, value in payload.items() if key not in ordered})
    print(json.dumps(ordered, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
