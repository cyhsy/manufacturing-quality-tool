"""质量域 Agent 取数封装。

调用链：``agents/quality_agent.py`` -> ``agent_tools/quality_tools.py``
-> ``tools/quality_tool.py`` -> ``data/quality.csv``

重要约定（S2-A-05）：
本模块**不重写质量系统**，只把项目已有的质量能力包装成 Agent 工具：

- 取数：``tools/quality_tool.query_quality_data()``
- 统计口径：``modules/quality_analysis.analyze_quality_overview()``
  与 ``modules/defect_analysis`` 中原有函数
- 根因知识：``modules/root_cause_engine``（原有根因知识库）
"""

from agent_tools import df_to_records, to_jsonable
from modules.defect_analysis import (
    DEFECT_COUNT_COLUMN,
    DEFECT_TYPE_COLUMN,
    RATIO_COLUMN,
    SEVERITY_COLUMN,
    summarize_by_defect_type,
    summarize_by_dimension,
)
from modules.quality_analysis import analyze_quality_overview
from modules.quality_knowledge import (
    list_categories,
    load_quality_cases,
    search_quality_knowledge,
)
from modules.root_cause_engine import (
    find_defect_root_causes,
    get_all_process_types,
    get_defect_types_for_process,
    get_root_causes,
)
from tools.production_tool import query_production_capacity
from tools.quality_tool import (
    list_defect_types,
    list_part_names,
    list_processes,
    query_quality_data,
)
from tools.traceability_tool import (
    filter_quality_records,
    load_product_mapping,
    map_quality_parts_to_products,
    query_traceability,
    resolve_quality_parts,
)


HIGH_SEVERITY_VALUE = "高"


def get_quality_records(
    process=None,
    defect_type=None,
    severity=None,
    handling_status=None,
):
    """取质量异常记录（DataFrame），委托 ``tools.quality_tool.query_quality_data()``。"""
    return query_quality_data(
        process=process,
        defect_type=defect_type,
        severity=severity,
        handling_status=handling_status,
    )


def get_quality_overview():
    """质量总览（JSON 友好的 dict），直接复用原有质量分析入口。

    原有 ``analyze_quality_overview()`` 返回的 defect_summary 是 DataFrame，
    这里转换为记录列表，保证 Agent 输出可直接 JSON 序列化。
    """
    overview = analyze_quality_overview()
    return {
        **{
            key: to_jsonable(value)
            for key, value in overview.items()
            if key != "defect_summary"
        },
        "defect_summary": df_to_records(overview["defect_summary"]),
    }


def get_defect_summary(limit=None):
    """缺陷类型汇总记录（dict 列表，按缺陷数量降序）。"""
    summary = analyze_quality_overview()["defect_summary"]
    if limit is not None and limit > 0:
        summary = summary.head(limit)
    return df_to_records(summary)


def get_severity_breakdown():
    """按严重等级汇总的记录（dict 列表），复用原有维度统计口径。"""
    records = query_quality_data()
    return df_to_records(summarize_by_dimension(records, SEVERITY_COLUMN))


def get_quality_risk_metrics():
    """质量风险指标：总缺陷、缺陷类型数、主要缺陷占比、高严重等级占比。

    「高严重等级占比」复用 ``summarize_by_dimension()`` 的原有统计口径，
    与页面上的规则摘要保持同一套算法。
    """
    records = query_quality_data()
    defect_summary = summarize_by_defect_type(records)

    total_defects = 0
    defect_type_count = 0
    top_defect_type = None
    top_defect_ratio = 0.0

    if not defect_summary.empty:
        total_defects = int(defect_summary[DEFECT_COUNT_COLUMN].sum())
        defect_type_count = int(len(defect_summary))
        top_row = defect_summary.iloc[0]
        top_defect_type = str(top_row[DEFECT_TYPE_COLUMN])
        top_defect_ratio = float(top_row[RATIO_COLUMN])

    severity_summary = summarize_by_dimension(records, SEVERITY_COLUMN)
    high_severity_ratio = 0.0
    if total_defects > 0 and not severity_summary.empty:
        high_rows = severity_summary.loc[
            severity_summary[SEVERITY_COLUMN].astype(str) == HIGH_SEVERITY_VALUE
        ]
        if not high_rows.empty:
            high_severity_ratio = float(
                high_rows[DEFECT_COUNT_COLUMN].iloc[0] / total_defects
            )

    return {
        "record_count": int(len(records)),
        "total_defects": total_defects,
        "defect_type_count": defect_type_count,
        "top_defect_type": top_defect_type,
        "top_defect_ratio": top_defect_ratio,
        "high_severity_ratio": high_severity_ratio,
    }


def get_root_cause_options():
    """原有根因知识库的可选范围：工序 -> 缺陷类型列表。"""
    return {
        process: list(get_defect_types_for_process(process))
        for process in get_all_process_types()
    }


def get_root_causes_for(process, defect_type):
    """按工序 + 缺陷类型查询原有根因知识库。"""
    if not process or not defect_type:
        return []
    return to_jsonable(get_root_causes(process, defect_type))


def find_root_causes(defect_type, process_hint=None):
    """按缺陷类型自动匹配工序并返回根因（复用原有匹配逻辑）。"""
    matched_process, causes = find_defect_root_causes(defect_type, process_hint)
    return {
        "defect_type": defect_type,
        "matched_process": matched_process,
        "causes": to_jsonable(causes),
    }


# --------------------------------------------------------------------------
# S4-A：质量议题分析相关取数
# --------------------------------------------------------------------------


def get_issue_records(
    product=None,
    batch=None,
    defect_type=None,
    process=None,
    start=None,
    end=None,
):
    """按议题条件取质量记录（DataFrame）。

    复用 ``tools.traceability_tool.filter_quality_records()`` 的统一过滤口径，
    避免追溯与议题分析出现两套筛选逻辑。
    """
    return filter_quality_records(
        product=product,
        batch=batch,
        defect=defect_type,
        process=process,
        start=start,
        end=end,
    )


def get_traceability(
    product=None,
    batch=None,
    defect=None,
    process=None,
    start=None,
    end=None,
    record_limit=20,
):
    """质量追溯（S4-A-02）：产品 / 批次 / 缺陷 -> 工序 / 设备 / 生产记录。"""
    return to_jsonable(
        query_traceability(
            product=product,
            batch=batch,
            defect=defect,
            process=process,
            start=start,
            end=end,
            record_limit=record_limit,
        )
    )


def search_improvement_knowledge(defect_type=None, process=None, category=None, limit=3):
    """检索质量改善知识库（S4-A-03）。

    委托 ``modules.quality_knowledge.search_quality_knowledge()``；
    置信度为「与知识库改善案例的匹配度」，不是责任判定。
    """
    observation = {"缺陷类型": defect_type, "工序": process, "类别": category}
    return to_jsonable(search_quality_knowledge(observation, limit=limit))


def get_quality_knowledge_summary():
    """质量改善知识库规模与类别分布。"""
    cases = load_quality_cases()
    return {"case_count": len(cases), "categories": list_categories(cases)}


def list_part_options():
    """可选零件名称（质量数据侧，用于实体识别）。"""
    return list_part_names()


def list_defect_options():
    """可选缺陷类型（质量数据侧）。"""
    return list_defect_types()


def list_process_options():
    """可选工序：质量数据工序 ∪ MES 工序。"""
    processes = set(list_processes())

    lines = query_production_capacity()
    if not lines.empty:
        processes.update(str(value) for value in lines["process"])

    return sorted(processes)


# --------------------------------------------------------------------------
# S4.1：产品映射层（MES 产品 <-> 质量零件）
# --------------------------------------------------------------------------


def get_product_mapping():
    """产品映射表记录（data/product_mapping.csv）。"""
    return df_to_records(load_product_mapping())


def get_mapped_quality_parts(product):
    """查询对象 -> 质量零件（复用产品映射层的解析口径）。"""
    return to_jsonable(resolve_quality_parts(product))


def get_products_for_quality_parts(quality_parts):
    """质量零件 -> MES 产品（反向映射，用于「影响产品」定位）。"""
    return map_quality_parts_to_products(quality_parts)
