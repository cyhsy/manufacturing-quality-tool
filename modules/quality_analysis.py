"""质量分析模块：原质量分析逻辑迁移后的统一入口。

迁移映射（原 src/ → 现 modules/）：

===========================================  ====================================
原路径                                        现路径
===========================================  ====================================
src/data_loader.py                           modules/quality_analysis.py（本文件）
src/defect_analysis.py                       modules/defect_analysis.py
src/charts.py                                modules/charts.py
src/demo_data.py                             modules/demo_data.py
src/root_cause_engine.py                     modules/root_cause_engine.py
src/report_generator.py                      modules/report_generator.py
src/word_report_generator.py                 modules/word_report_generator.py
src/llm_quality_analysis.py                  modules/llm_quality_analysis.py
===========================================  ====================================

迁移原则：
1. 原有对外函数签名、字段校验口径和返回结构保持不变，仅把 import 前缀
   `src.` 改为 `modules.`，因此原有质量分析功能不受影响。
2. 在本文件底部新增面向内置质量数据 `data/quality.csv` 的便捷入口，
   供「制造运营中心」驾驶舱直接复用原有质量分析能力（不重复实现分析口径）。
"""

from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = [
    "日期",
    "批次号",
    "零件编号",
    "零件名称",
    "工序",
    "缺陷类型",
    "缺陷数量",
    "批次数量",
    "供应商",
    "责任部门",
    "严重等级",
    "处理状态",
]

# 项目根目录 => data/quality.csv（原质量数据）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_DATA_PATH = PROJECT_ROOT / "data" / "quality.csv"


def load_quality_file(uploaded_file):
    """Load an uploaded quality data file into a pandas DataFrame.

    与迁移前 src/data_loader.py 的行为完全一致：
    csv 先按 utf-8-sig 解析，失败后回退 gbk；xlsx/xls 走 read_excel。
    """
    file_name = uploaded_file.name
    suffix = Path(file_name).suffix.lower()

    if suffix == ".csv":
        try:
            return pd.read_csv(uploaded_file, encoding="utf-8-sig")
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="gbk")

    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(uploaded_file)

    raise ValueError("不支持的文件类型。请上传 csv、xlsx 或 xls 文件。")


def validate_required_columns(df):
    """Return the required columns that are missing from the DataFrame."""
    return [column for column in REQUIRED_COLUMNS if column not in df.columns]


# ---------------------------------------------------------------------------
# 以下为本次新增：内置质量数据（data/quality.csv）入口，复用原有分析口径
# ---------------------------------------------------------------------------


def load_quality_dataframe(path=None):
    """读取内置质量数据 data/quality.csv。

    参数：
        path: 可选，自定义质量数据文件路径；默认使用 data/quality.csv。

    返回：
        pandas.DataFrame，字段与上传文件解析结果一致。
    """
    quality_path = Path(path) if path is not None else QUALITY_DATA_PATH
    if not quality_path.is_file():
        raise FileNotFoundError(f"质量数据文件不存在：{quality_path}")
    return pd.read_csv(quality_path, encoding="utf-8-sig")


def analyze_quality_overview(df=None):
    """复用原有质量分析逻辑，汇总驾驶舱「质量」模块所需的指标。

    参数：
        df: 可选的质量数据 DataFrame；缺省时读取 data/quality.csv。

    返回 dict：
        total_defect_count  总缺陷数量
        record_count        质量记录条数
        defect_type_count   缺陷类型数量
        top_defect_type     缺陷数量最高的缺陷类型（无数据时为 None）
        top_defect_count    最高缺陷类型的缺陷数量
        defect_summary      缺陷类型汇总表（缺陷类型/缺陷数量/占比）
        summary_lines       原 generate_quality_summary 生成的摘要句子列表
        missing_columns     缺失的必要字段（无缺失时为空列表）
    """
    from modules.defect_analysis import (
        generate_quality_summary,
        summarize_by_defect_type,
    )

    quality_df = load_quality_dataframe() if df is None else df
    missing_columns = validate_required_columns(quality_df)

    defect_summary = summarize_by_defect_type(quality_df)
    total_defect_count = int(defect_summary["缺陷数量"].sum()) if not defect_summary.empty else 0
    top_defect = defect_summary.iloc[0] if not defect_summary.empty else None

    return {
        "total_defect_count": total_defect_count,
        "record_count": int(len(quality_df)),
        "defect_type_count": int(len(defect_summary)),
        "top_defect_type": None if top_defect is None else str(top_defect["缺陷类型"]),
        "top_defect_count": 0 if top_defect is None else int(top_defect["缺陷数量"]),
        "defect_summary": defect_summary,
        "summary_lines": list(generate_quality_summary(quality_df)),
        "missing_columns": missing_columns,
    }
