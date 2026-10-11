"""维修工单工具（S3-A-03）。

调用链：``agents/equipment_agent.py`` -> ``agent_tools/work_order_tools.py``
-> ``tools``（工单文件路径与读取）+ ``data/work_orders.csv``（追加写入）

生成规则：

- **维修编号**：``WO-YYYYMMDD-NNN``，按当天已有工单顺序递增（跨天从 001 重新开始）；
- **优先级**：显式指定 > 设备状态（fault→紧急、warning→高） > 诊断置信度（≥0.8→高） > 普通；
- **负责人**：显式指定 > 按设备类型分配到维修班组（CNC/铣削/钻削→机加维修组 等）；
- **建议时间**：创建时间 + 响应时限（紧急 4h / 高 24h / 普通 72h）；
- **落库**：``persist=True`` 时追加到 ``data/work_orders.csv``；
  ``persist=False`` 只生成工单记录，供 Agent 做只读分析。

写入约定：新建文件写表头时使用 UTF-8 BOM（便于 Excel 打开），
追加时使用不带 BOM 的 UTF-8，避免 BOM 出现在文件中间；读取统一用 utf-8-sig 兼容两者。
"""

from datetime import timedelta
from pathlib import Path

import pandas as pd

from agent_tools import to_jsonable
from tools import DATA_DIR, read_data_csv


WORK_ORDER_FILE_NAME = "work_orders.csv"
WORK_ORDER_PATH = DATA_DIR / WORK_ORDER_FILE_NAME

WORK_ORDER_COLUMNS = [
    "维修编号",
    "设备",
    "故障",
    "优先级",
    "负责人",
    "建议时间",
    "创建时间",
    "状态",
    "来源",
    "依据",
]

PRIORITY_RESPONSE_HOURS = {"紧急": 4, "高": 24, "普通": 72}
EQUIPMENT_STATUS_PRIORITY = {"fault": "紧急", "warning": "高", "normal": "普通"}

OWNER_BY_EQUIPMENT_TYPE = {
    "CNC": "机加维修组",
    "MILLING": "机加维修组",
    "DRILLING": "机加维修组",
    "CASTING": "铸造维修组",
    "GRINDING": "磨削维修组",
    "WELDING": "焊接维修组",
    "HEAT_TREATMENT": "热处理维修组",
    "ASSEMBLY": "装配维修组",
    "TESTING": "检测维修组",
    "ELECTRICAL": "电气维修组",
}
DEFAULT_OWNER = "设备维修组"


def resolve_priority(equipment_status=None, confidence=None, priority=None):
    """推断工单优先级：显式指定 > 设备状态 > 诊断置信度。"""
    if priority:
        return str(priority)

    status = str(equipment_status or "").strip().lower()
    if status in EQUIPMENT_STATUS_PRIORITY:
        return EQUIPMENT_STATUS_PRIORITY[status]

    if confidence is not None and float(confidence) >= 0.8:
        return "高"

    return "普通"


def resolve_owner(equipment_type=None, owner=None):
    """推断负责人：显式指定 > 按设备类型分配维修班组。"""
    if owner:
        return str(owner)
    return OWNER_BY_EQUIPMENT_TYPE.get(str(equipment_type or "").strip().upper(), DEFAULT_OWNER)


def next_work_order_id(created_at, existing_ids=None):
    """生成维修编号 ``WO-YYYYMMDD-NNN``。"""
    prefix = f"WO-{pd.Timestamp(created_at).strftime('%Y%m%d')}-"
    sequence = 1

    for value in existing_ids if existing_ids is not None else []:
        text = str(value)
        if not text.startswith(prefix):
            continue
        try:
            sequence = max(sequence, int(text.rsplit("-", 1)[1]) + 1)
        except (IndexError, ValueError):
            continue

    return f"{prefix}{sequence:03d}"


def load_work_orders(path=None):
    """读取全部维修工单（DataFrame）；文件不存在时返回同结构空表。"""
    target = Path(path) if path is not None else WORK_ORDER_PATH
    try:
        return read_data_csv(WORK_ORDER_FILE_NAME, WORK_ORDER_COLUMNS, path=target)
    except FileNotFoundError:
        return pd.DataFrame(columns=WORK_ORDER_COLUMNS)


def append_work_order(record, path=None):
    """把一条工单追加到 CSV；文件不存在时先写表头。"""
    target = Path(path) if path is not None else WORK_ORDER_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame([record], columns=WORK_ORDER_COLUMNS)
    is_new_file = not target.is_file() or target.stat().st_size == 0

    if is_new_file:
        frame.to_csv(target, mode="w", header=True, index=False, encoding="utf-8-sig")
    else:
        frame.to_csv(target, mode="a", header=False, index=False, encoding="utf-8")

    return str(target)


def create_work_order(
    equipment,
    fault,
    priority=None,
    owner=None,
    suggested_time=None,
    equipment_status=None,
    equipment_type=None,
    confidence=None,
    evidence=None,
    source="equipment_agent",
    persist=True,
    path=None,
    created_at=None,
):
    """创建维修工单，返回工单记录（dict）。

    生成字段：维修编号 / 设备 / 故障 / 优先级 / 负责人 / 建议时间
    （另含 创建时间 / 状态 / 来源 / 依据，便于追溯）。

    参数：
        equipment:        设备编号，如 "CNC02"。
        fault:            故障名称，如 "主轴轴承异常"。
        priority:         优先级，缺省按设备状态/置信度推断。
        owner:            负责人/班组，缺省按设备类型推断。
        suggested_time:   建议时间，缺省按优先级响应时限计算。
        equipment_status: 设备状态（fault / warning / normal），用于推断优先级。
        equipment_type:   设备类型（CNC / WELDING ...），用于推断负责人。
        confidence:       诊断置信度（0~1），用于推断优先级。
        evidence:         诊断依据文本。
        source:           工单来源标识。
        persist:          是否落库到 data/work_orders.csv。
        path:             自定义工单文件路径（测试用）。
        created_at:       创建时间（缺省当前时间，测试可固定）。
    """
    created = pd.Timestamp(created_at) if created_at is not None else pd.Timestamp.now()
    target = Path(path) if path is not None else WORK_ORDER_PATH

    existing = load_work_orders(target)
    existing_ids = [] if existing.empty else list(existing["维修编号"])

    resolved_priority = resolve_priority(
        equipment_status=equipment_status,
        confidence=confidence,
        priority=priority,
    )
    response_hours = PRIORITY_RESPONSE_HOURS.get(
        resolved_priority, PRIORITY_RESPONSE_HOURS["普通"]
    )
    suggested = (
        pd.Timestamp(suggested_time)
        if suggested_time is not None
        else created + timedelta(hours=response_hours)
    )

    record = {
        "维修编号": next_work_order_id(created, existing_ids),
        "设备": str(equipment),
        "故障": str(fault),
        "优先级": resolved_priority,
        "负责人": resolve_owner(equipment_type=equipment_type, owner=owner),
        "建议时间": suggested.isoformat(),
        "创建时间": created.isoformat(),
        "状态": "待处理",
        "来源": str(source),
        "依据": str(evidence or ""),
    }

    if persist:
        append_work_order(record, target)

    return to_jsonable(record)


def query_work_orders(equipment=None, priority=None, path=None):
    """查询维修工单（DataFrame），可按设备与优先级筛选。"""
    frame = load_work_orders(path)
    if frame.empty:
        return frame

    if equipment is not None:
        frame = frame.loc[frame["设备"].astype(str) == str(equipment)]
    if priority is not None:
        frame = frame.loc[frame["优先级"].astype(str) == str(priority)]

    return frame.reset_index(drop=True)
