from io import BytesIO

import pandas as pd

from src.defect_analysis import (
    PART_NAME_COLUMN,
    PROCESS_COLUMN,
    SEVERITY_COLUMN,
    SUPPLIER_COLUMN,
    generate_quality_summary,
    prepare_pareto_data,
    summarize_by_dimension,
)


def _message_df(message):
    return pd.DataFrame({"提示": [message]})


def _build_dimension_summary(df, dimension_col):
    try:
        return summarize_by_dimension(df, dimension_col)
    except ValueError:
        return _message_df(f"缺少字段：{dimension_col}，无法生成该维度统计。")


def _build_defect_type_summary(df):
    try:
        return prepare_pareto_data(df)
    except ValueError:
        return _message_df("缺少字段：缺陷类型或缺陷数量，无法生成缺陷类型统计。")


def build_excel_report(df):
    """Build an Excel analysis report in memory and return it as bytes."""
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if df.empty:
            _message_df("当前数据为空，未生成统计结果。").to_excel(
                writer,
                sheet_name="原始数据",
                index=False,
            )
        else:
            df.to_excel(writer, sheet_name="原始数据", index=False)

        _build_defect_type_summary(df).to_excel(
            writer,
            sheet_name="缺陷类型统计",
            index=False,
        )
        _build_dimension_summary(df, PART_NAME_COLUMN).to_excel(
            writer,
            sheet_name="零件统计",
            index=False,
        )
        _build_dimension_summary(df, PROCESS_COLUMN).to_excel(
            writer,
            sheet_name="工序统计",
            index=False,
        )
        _build_dimension_summary(df, SUPPLIER_COLUMN).to_excel(
            writer,
            sheet_name="供应商统计",
            index=False,
        )
        _build_dimension_summary(df, SEVERITY_COLUMN).to_excel(
            writer,
            sheet_name="严重等级统计",
            index=False,
        )

        summary_items = generate_quality_summary(df)
        pd.DataFrame({"质量分析摘要": summary_items}).to_excel(
            writer,
            sheet_name="质量分析摘要",
            index=False,
        )

    return output.getvalue()
