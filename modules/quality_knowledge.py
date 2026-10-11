"""质量改善知识库检索（knowledge/quality/*.md），S4-A-03。

知识库格式（每条案例一个 Markdown 文件）：

    # 尺寸偏大

    案例编号: QI-001
    类别: 尺寸异常
    适用工序: 车削, 铣削
    关联缺陷: 尺寸偏大

    现象:
    实测尺寸超出上偏差

    原因:
    刀具磨损导致切削力变化

    验证方法:
    三坐标测量机复测首末件

    改善措施:
    按刀具寿命强制换刀

检索打分（确定性、可解释、无外部依赖）：

    ========================  ======
    命中项                     权重
    ========================  ======
    关联缺陷命中（缺陷类型一致）  +3.0
    适用工序命中                 +2.0
    类别命中                     +1.5
    ========================  ======

置信度 = ``min(0.95, 总分 / 6)``；低于 3.0 分（即缺陷未命中）不视为匹配；
排序固定为（总分降序、关联缺陷命中优先、案例编号升序），保证结果可复现。

注意：置信度表示「与知识库改善案例的匹配度」，不是缺陷责任判定或放行结论。
"""

from pathlib import Path

from modules.knowledge_base import parse_case_text, split_list


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge" / "quality"

SECTION_KEYS = ("现象", "原因", "验证方法", "改善措施")
METADATA_KEYS = ("案例编号", "类别", "适用工序", "关联缺陷")

DEFECT_WEIGHT = 3.0
PROCESS_WEIGHT = 2.0
CATEGORY_WEIGHT = 1.5
MAX_SCORE = 6.0
CONFIDENCE_CAP = 0.95
MIN_MATCH_SCORE = 3.0

CATEGORIES = ("尺寸异常", "表面缺陷", "铸造缺陷", "装配异常")


def parse_case(text, fallback_title=""):
    """解析单条质量改善案例 -> dict。"""
    title, metadata, sections = parse_case_text(
        text,
        section_keys=SECTION_KEYS,
        metadata_keys=METADATA_KEYS,
        fallback_title=fallback_title,
    )

    return {
        "案例编号": metadata.get("案例编号", fallback_title),
        "标题": title or fallback_title,
        "类别": metadata.get("类别", ""),
        "适用工序": split_list(metadata.get("适用工序", "")),
        "关联缺陷": split_list(metadata.get("关联缺陷", "")),
        "现象": sections.get("现象", []),
        "原因": sections.get("原因", []),
        "验证方法": sections.get("验证方法", []),
        "改善措施": sections.get("改善措施", []),
    }


def load_quality_cases(directory=None):
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


def list_categories(cases=None):
    """知识库覆盖的缺陷类别及其案例数。"""
    summary = {}
    for case in cases if cases is not None else load_quality_cases():
        category = case["类别"] or "未分类"
        summary[category] = summary.get(category, 0) + 1
    return summary


def score_case(case, observation):
    """给单条案例打分，返回分值与命中依据。"""
    score = 0.0
    evidence = []

    defect_type = str(observation.get("缺陷类型") or "").strip()
    process = str(observation.get("工序") or "").strip()
    category = str(observation.get("类别") or "").strip()

    if defect_type and defect_type in case["关联缺陷"]:
        score += DEFECT_WEIGHT
        evidence.append(f"关联缺陷命中：{defect_type}")

    if process and process in case["适用工序"]:
        score += PROCESS_WEIGHT
        evidence.append(f"适用工序命中：{process}")

    if category and category == case["类别"]:
        score += CATEGORY_WEIGHT
        evidence.append(f"类别命中：{category}")

    return {"score": round(score, 2), "evidence": evidence}


def search_quality_knowledge(observation, limit=3, directory=None, min_score=MIN_MATCH_SCORE):
    """检索最匹配的质量改善案例。

    参数：
        observation: 查询条件 dict，支持键：``缺陷类型`` / ``工序`` / ``类别``。
        limit:       返回条数上限（None 表示全部）。
        directory:   自定义知识库目录（测试用）。
        min_score:   视为匹配的最低分。

    返回：
        list[dict]，案例原始字段 + ``score`` / ``confidence`` / ``命中依据``。
    """
    observation = dict(observation or {})

    matches = []
    for case in load_quality_cases(directory):
        scored = score_case(case, observation)
        if scored["score"] < min_score:
            continue

        matches.append(
            {
                **case,
                "score": scored["score"],
                "confidence": min(CONFIDENCE_CAP, round(scored["score"] / MAX_SCORE, 2)),
                "命中依据": scored["evidence"],
            }
        )

    matches.sort(
        key=lambda item: (
            -item["score"],
            0 if observation.get("缺陷类型") in item["关联缺陷"] else 1,
            item["案例编号"],
        )
    )

    if limit is not None and limit > 0:
        return matches[:limit]
    return matches
