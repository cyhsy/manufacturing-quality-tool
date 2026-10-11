"""质量数据读取工具：原质量数据（data/quality.csv）。

分层说明：
    本工具只负责读取原始质量记录（数据访问层）。
    缺陷统计、占比、摘要等分析口径统一由 modules/quality_analysis.py 复用原有
    质量分析逻辑生成（分析层），避免出现两套统计口径。
"""

from modules.quality_analysis import REQUIRED_COLUMNS
from tools import filter_by_values, read_data_csv


QUALITY_COLUMNS = list(REQUIRED_COLUMNS)

PROCESS_COLUMN = "工序"
DEFECT_TYPE_COLUMN = "缺陷类型"
SEVERITY_COLUMN = "严重等级"
HANDLING_STATUS_COLUMN = "处理状态"
PART_NAME_COLUMN = "零件名称"
PART_CODE_COLUMN = "零件编号"
BATCH_COLUMN = "批次号"


def query_quality_data(
    process=None,
    defect_type=None,
    severity=None,
    handling_status=None,
):
    """查询质量异常记录。

    参数：
        process:         工序筛选，单值或列表。
        defect_type:     缺陷类型筛选，单值或列表。
        severity:        严重等级筛选，单值或列表，如 "高"。
        handling_status: 处理状态筛选，单值或列表，如 "待处理"。

    返回：
        pandas.DataFrame，字段与 quality.csv 一致（含"备注"等可选字段）；
        无匹配记录时返回同结构空表。
    """
    # 质量数据额外带有"备注"列，因此只校验必需字段，不限制总列数。
    df = read_data_csv("quality.csv", QUALITY_COLUMNS)

    df = filter_by_values(df, PROCESS_COLUMN, process)
    df = filter_by_values(df, DEFECT_TYPE_COLUMN, defect_type)
    df = filter_by_values(df, SEVERITY_COLUMN, severity)
    df = filter_by_values(df, HANDLING_STATUS_COLUMN, handling_status)

    return df.reset_index(drop=True)


def _unique_values(column):
    """质量数据中某字段的去重取值（升序）。"""
    df = query_quality_data()
    if df.empty or column not in df.columns:
        return []
    return sorted({str(value) for value in df[column].dropna()})


def list_part_names():
    """全部零件名称（升序）。"""
    return _unique_values(PART_NAME_COLUMN)


def list_part_codes():
    """全部零件编号（升序）。"""
    return _unique_values(PART_CODE_COLUMN)


def list_defect_types():
    """全部缺陷类型（升序）。"""
    return _unique_values(DEFECT_TYPE_COLUMN)


def list_processes():
    """质量数据中出现过的工序（升序）。"""
    return _unique_values(PROCESS_COLUMN)


def list_batches():
    """全部批次号（升序）。"""
    return _unique_values(BATCH_COLUMN)
