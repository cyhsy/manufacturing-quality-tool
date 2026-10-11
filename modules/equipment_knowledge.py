"""设备故障知识库检索（knowledge/equipment/*.md），S3-A-01 / S3-A-02 依赖。

知识库格式（每条案例一个 Markdown 文件）：

    # 主轴温升异常

    案例编号: EQ-001
    适用设备: CNC / 加工中心
    关联信号: 温度, 主轴, 润滑
    优先级: 高

    现象:
    温度>90℃
    主轴温度持续上升

    可能原因:
    轴承磨损
    润滑不足

    处理:
    检查润滑系统
    更换轴承

检索方式（v1：确定性、可解释、无外部依赖）：

1. 解析每条案例的「现象 / 可能原因 / 处理 / 适用设备 / 关联信号 / 优先级」；
2. 从观测数据（设备状态、产线状态、传感器读数、报警文本）构造症状；
   只有**异常设备**才参与信号匹配，正常设备不会命中案例；
3. 打分：

   ====================================  ======
   命中项                                 权重
   ====================================  ======
   数值条件命中（如 温度>90℃ 且实测 95℃）  +3.0
   关联信号命中                            +1.5
   适用设备类型命中                        +1.5
   ====================================  ======

4. 置信度 = ``min(0.95, 总分 / 7)``；低于 3.0 分不视为匹配；
   排序固定为（总分降序、数值条件命中数降序、高优先级优先、案例编号升序），保证结果可复现。

注意：置信度表示「与知识库案例的相似度」，不是工程失效概率或放行判定。
"""

import re
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge" / "equipment"

SECTION_KEYS = ("现象", "可能原因", "处理")
METADATA_KEYS = ("案例编号", "适用设备", "关联信号", "优先级")

# 可参与数值比对的信号（与 iot_sensor.csv 的字段对应）
NUMERIC_CONDITION_PATTERN = re.compile(
    r"(温度|振动|电流|压力|转速)\s*(>=|>|≥|<|<=|≤)\s*(\d+(?:\.\d+)?)"
)

# 报警文本 -> 症状信号
SIGNAL_KEYWORDS = {
    "温度": ("温度", "温升", "过热", "烫"),
    "振动": ("振动", "异响", "噪声", "振纹"),
    "电流": ("电流", "过载", "过流"),
    "压力": ("压力", "气压", "液压"),
    "转速": ("转速", "打滑"),
}

NUMERIC_WEIGHT = 3.0
SIGNAL_WEIGHT = 1.5
EQUIPMENT_WEIGHT = 1.5
MAX_SCORE = 7.0
CONFIDENCE_CAP = 0.95
MIN_MATCH_SCORE = 3.0

HIGH_PRIORITY = "高"


def parse_case(text, fallback_title=""):
    """解析单条案例 Markdown -> dict。"""
    title = ""
    metadata = {}
    sections = {key: [] for key in SECTION_KEYS}
    current_section = None

    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#"):
            if not title:
                title = line.lstrip("#").strip()
            continue

        # 段落标题，例如 "现象:"
        if line.endswith((":", "：")):
            name = line[:-1].strip()
            if name in SECTION_KEYS:
                current_section = name
                continue

        matched = False
        if ":" in line or "：" in line:
            separator = ":" if ":" in line else "："
            key, _, value = line.partition(separator)
            key = key.strip()
            value = value.strip()

            if key in SECTION_KEYS and value:
                sections[key].append(value)
                current_section = key
                matched = True
            elif key in METADATA_KEYS:
                metadata[key] = value
                current_section = None
                matched = True

        if not matched and current_section:
            sections[current_section].append(line.lstrip("-").strip())

    signals = [
        item.strip()
        for item in re.split(r"[,，、]", metadata.get("关联信号", ""))
        if item.strip()
    ]

    return {
        "案例编号": metadata.get("案例编号", fallback_title),
        "标题": title or fallback_title,
        "适用设备": metadata.get("适用设备", ""),
        "关联信号": signals,
        "优先级": metadata.get("优先级", "中"),
        "现象": sections["现象"],
        "可能原因": sections["可能原因"],
        "处理": sections["处理"],
    }


def load_equipment_cases(directory=None):
    """加载知识库全部案例（按文件名排序，保证顺序稳定）。"""
    knowledge_dir = Path(directory) if directory is not None else KNOWLEDGE_DIR
    if not knowledge_dir.is_dir():
        return []

    cases = []
    for path in sorted(knowledge_dir.glob("*.md")):
        cases.append(
            parse_case(path.read_text(encoding="utf-8"), fallback_title=path.stem)
        )
    return cases


def numeric_conditions(case):
    """提取案例现象中的数值条件：(信号, 比较符, 阈值)。"""
    conditions = []
    for line in case.get("现象", []):
        for match in NUMERIC_CONDITION_PATTERN.finditer(line):
            conditions.append((match.group(1), match.group(2), float(match.group(3))))
    return conditions


def _as_float(value):
    if value is None:
        return None
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(number) else float(number)


def _compare(value, operator, threshold):
    if operator in (">", "≥"):
        return value > threshold if operator == ">" else value >= threshold
    if operator in ("<", "≤"):
        return value < threshold if operator == "<" else value <= threshold
    if operator == ">=":
        return value >= threshold
    if operator == "<=":
        return value <= threshold
    return False


def build_symptoms(observation):
    """把观测数据转成打分用的症状（只有异常设备才参与信号匹配）。"""
    observation = dict(observation or {})

    values = {
        "温度": _as_float(observation.get("温度")),
        "振动": _as_float(observation.get("振动")),
        "电流": _as_float(observation.get("电流")),
    }

    equipment_status = str(observation.get("equipment_status", "")).lower()
    production_status = str(observation.get("production_status", "")).lower()
    sensor_status = str(observation.get("sensor_status", "")).lower()
    text = str(observation.get("text", ""))

    abnormal = bool(observation.get("alarm")) or (
        equipment_status not in ("", "normal")
        or production_status in ("stopped", "maintenance")
        or sensor_status not in ("", "normal")
    )

    terms = set()
    if abnormal:
        terms.update(name for name, value in values.items() if value is not None)

    lowered = text.lower()
    for name, keywords in SIGNAL_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            terms.add(name)

    return {
        "values": values,
        "terms": terms,
        "abnormal": abnormal,
        "equipment_type": str(observation.get("equipment_type", "")),
        "text": text,
    }


def score_case(case, symptoms):
    """给单条案例打分，返回分值与命中依据。"""
    score = 0.0
    condition_hits = 0
    evidence = []

    for signal, operator, threshold in numeric_conditions(case):
        value = symptoms["values"].get(signal)
        if value is None:
            continue
        if _compare(value, operator, threshold):
            score += NUMERIC_WEIGHT
            condition_hits += 1
            evidence.append(f"{signal}{operator}{threshold:g} 命中（实测 {value:g}）")

    for signal in case.get("关联信号", []):
        if signal in SIGNAL_KEYWORDS and signal in symptoms["terms"]:
            score += SIGNAL_WEIGHT
            evidence.append(f"关联信号命中：{signal}")

    equipment_type = symptoms["equipment_type"]
    applicable = case.get("适用设备", "")
    if equipment_type and applicable and equipment_type.lower() in applicable.lower():
        score += EQUIPMENT_WEIGHT
        evidence.append(f"适用设备命中：{applicable}")

    return {
        "score": round(score, 2),
        "condition_hits": condition_hits,
        "evidence": evidence,
    }


def search_equipment_knowledge(observation, limit=3, directory=None, min_score=MIN_MATCH_SCORE):
    """检索最相似的设备故障案例。

    参数：
        observation: 观测数据 dict，支持键：
                     ``温度`` / ``振动`` / ``电流`` / ``equipment_status`` /
                     ``production_status`` / ``sensor_status`` / ``alarm`` /
                     ``equipment_type`` / ``text``。
        limit:       返回条数上限（None 表示全部）。
        directory:   自定义知识库目录（测试用）。
        min_score:   视为匹配的最低分。

    返回：
        list[dict]，按固定规则排序，每项包含案例原始字段 +
        ``score`` / ``confidence`` / ``condition_hits`` / ``命中依据``。
    """
    symptoms = build_symptoms(observation)

    matches = []
    for case in load_equipment_cases(directory):
        scored = score_case(case, symptoms)
        if scored["score"] < min_score:
            continue

        matches.append(
            {
                **case,
                "score": scored["score"],
                "condition_hits": scored["condition_hits"],
                "confidence": min(CONFIDENCE_CAP, round(scored["score"] / MAX_SCORE, 2)),
                "命中依据": scored["evidence"],
            }
        )

    matches.sort(
        key=lambda item: (
            -item["score"],
            -item["condition_hits"],
            0 if item["优先级"] == HIGH_PRIORITY else 1,
            item["案例编号"],
        )
    )

    if limit is not None and limit > 0:
        return matches[:limit]
    return matches
