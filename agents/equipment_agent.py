"""Equipment Agent：设备健康与维保分析。

取数来源（全部经 agent_tools 封装）：

- ``agent_tools.equipment_tools.get_equipment()``    -> ``tools.equipment_tool.query_equipment_status()``
- ``agent_tools.equipment_tools.get_sensor_readings()`` -> ``tools.read_data_csv("iot_sensor.csv")``

判定口径：

- 设备故障（fault）           -> high（相关工序产能为 0）
- 存在预警（warning）设备      -> medium
- 传感器告警（warning/alarm）  -> 至少 medium
- 维保超期                    -> 计入 reason 与 suggestion
"""

from agent_tools import equipment_tools
from modules.equipment_analysis import DEFAULT_MAINTENANCE_INTERVAL_DAYS


def analyze_equipment_status(today=None):
    """设备健康分析：返回结构化的 risk / reason / suggestion 与明细。"""
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


def run(capabilities=None, arguments=None):
    """Agent 统一入口（equipment_agent 只提供设备能力）。"""
    capabilities = list(capabilities or ["equipment"])
    arguments = dict(arguments or {})

    result = analyze_equipment_status(today=arguments.get("today"))
    result["capabilities"] = capabilities
    return result


def main():
    """命令行入口：``python -m agents.equipment_agent``。"""
    import json

    print(json.dumps(run(capabilities=["equipment"]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
