import pandas as pd


DEFECT_TYPE_COLUMN = "缺陷类型"
DEFECT_COUNT_COLUMN = "缺陷数量"
DATE_COLUMN = "日期"
RATIO_COLUMN = "占比"
CUMULATIVE_RATIO_COLUMN = "累计占比"
RECORD_COUNT_COLUMN = "记录数"
PART_NAME_COLUMN = "零件名称"
PROCESS_COLUMN = "工序"
SUPPLIER_COLUMN = "供应商"
SEVERITY_COLUMN = "严重等级"
HIGH_SEVERITY_VALUE = "高"


def format_percent(ratio):
    """Format a decimal ratio as a percentage string."""
    return f"{ratio * 100:.2f}%"


def summarize_by_dimension(df, dimension_col):
    """Summarize defect counts, record counts, and ratios by one dimension."""
    required_columns = [dimension_col, DEFECT_COUNT_COLUMN]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError("缺少必要字段：" + "、".join(missing_columns))

    result_columns = [
        dimension_col,
        DEFECT_COUNT_COLUMN,
        RECORD_COUNT_COLUMN,
        RATIO_COLUMN,
    ]
    if df.empty:
        return pd.DataFrame(columns=result_columns)

    data = df[[dimension_col, DEFECT_COUNT_COLUMN]].copy()
    data[DEFECT_COUNT_COLUMN] = pd.to_numeric(
        data[DEFECT_COUNT_COLUMN],
        errors="coerce",
    ).fillna(0)

    summary = (
        data.groupby(dimension_col, as_index=False)
        .agg(
            **{
                DEFECT_COUNT_COLUMN: (DEFECT_COUNT_COLUMN, "sum"),
                RECORD_COUNT_COLUMN: (DEFECT_COUNT_COLUMN, "size"),
            }
        )
        .sort_values(DEFECT_COUNT_COLUMN, ascending=False)
        .reset_index(drop=True)
    )

    total_defect_count = summary[DEFECT_COUNT_COLUMN].sum()
    if total_defect_count == 0:
        summary[RATIO_COLUMN] = 0
    else:
        summary[RATIO_COLUMN] = summary[DEFECT_COUNT_COLUMN] / total_defect_count

    return summary[result_columns]


def get_top_dimension_item(summary_df):
    """Return the row with the highest defect count from a dimension summary."""
    if summary_df.empty:
        return None

    return summary_df.iloc[0]


def summarize_by_date(df):
    """Summarize defect counts and record counts by date."""
    required_columns = [DATE_COLUMN, DEFECT_COUNT_COLUMN]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError("缺少必要字段：" + "、".join(missing_columns))

    result_columns = [DATE_COLUMN, DEFECT_COUNT_COLUMN, RECORD_COUNT_COLUMN]
    if df.empty:
        return pd.DataFrame(columns=result_columns)

    data = df[[DATE_COLUMN, DEFECT_COUNT_COLUMN]].copy()
    data[DATE_COLUMN] = pd.to_datetime(data[DATE_COLUMN], errors="coerce").dt.date
    data[DEFECT_COUNT_COLUMN] = pd.to_numeric(
        data[DEFECT_COUNT_COLUMN],
        errors="coerce",
    ).fillna(0)
    data = data.dropna(subset=[DATE_COLUMN])

    if data.empty:
        return pd.DataFrame(columns=result_columns)

    summary = (
        data.groupby(DATE_COLUMN, as_index=False)
        .agg(
            **{
                DEFECT_COUNT_COLUMN: (DEFECT_COUNT_COLUMN, "sum"),
                RECORD_COUNT_COLUMN: (DEFECT_COUNT_COLUMN, "size"),
            }
        )
        .sort_values(DATE_COLUMN, ascending=True)
        .reset_index(drop=True)
    )

    return summary[result_columns]


def get_top_defect_date(date_summary_df):
    """Return the date row with the highest defect count from a date summary."""
    if date_summary_df.empty:
        return None

    return date_summary_df.sort_values(
        DEFECT_COUNT_COLUMN,
        ascending=False,
    ).iloc[0]


def filter_records_by_date(df, target_date):
    """Filter original records by one target date."""
    if DATE_COLUMN not in df.columns:
        raise ValueError("缺少必要字段：" + DATE_COLUMN)

    if df.empty:
        return df.copy()

    target = pd.to_datetime(target_date, errors="coerce")
    if pd.isna(target):
        return df.iloc[0:0].copy()

    data = df.copy()
    record_dates = pd.to_datetime(data[DATE_COLUMN], errors="coerce").dt.date
    return data.loc[record_dates == target.date()].copy()


def summarize_by_defect_type(df):
    """Summarize defect counts and ratios by defect type."""
    required_columns = [DEFECT_TYPE_COLUMN, DEFECT_COUNT_COLUMN]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError("缺少必要字段：" + "、".join(missing_columns))

    if df.empty:
        return pd.DataFrame(columns=[DEFECT_TYPE_COLUMN, DEFECT_COUNT_COLUMN, RATIO_COLUMN])

    data = df[[DEFECT_TYPE_COLUMN, DEFECT_COUNT_COLUMN]].copy()
    data[DEFECT_COUNT_COLUMN] = pd.to_numeric(
        data[DEFECT_COUNT_COLUMN],
        errors="coerce",
    ).fillna(0)

    summary = (
        data.groupby(DEFECT_TYPE_COLUMN, as_index=False)[DEFECT_COUNT_COLUMN]
        .sum()
        .sort_values(DEFECT_COUNT_COLUMN, ascending=False)
        .reset_index(drop=True)
    )

    total_defect_count = summary[DEFECT_COUNT_COLUMN].sum()
    if total_defect_count == 0:
        summary[RATIO_COLUMN] = 0
    else:
        summary[RATIO_COLUMN] = summary[DEFECT_COUNT_COLUMN] / total_defect_count

    return summary


def prepare_pareto_data(df):
    """Prepare defect type counts, ratios, and cumulative ratios for a Pareto chart."""
    summary = summarize_by_defect_type(df)

    if summary.empty:
        return pd.DataFrame(
            columns=[
                DEFECT_TYPE_COLUMN,
                DEFECT_COUNT_COLUMN,
                RATIO_COLUMN,
                CUMULATIVE_RATIO_COLUMN,
            ]
        )

    total_defect_count = summary[DEFECT_COUNT_COLUMN].sum()
    if total_defect_count == 0:
        summary[CUMULATIVE_RATIO_COLUMN] = 0
    else:
        summary[CUMULATIVE_RATIO_COLUMN] = summary[RATIO_COLUMN].cumsum()

    return summary


def generate_quality_summary(df):
    """Generate rule-based quality analysis summary sentences."""
    required_columns = [
        DEFECT_TYPE_COLUMN,
        DEFECT_COUNT_COLUMN,
        PART_NAME_COLUMN,
        PROCESS_COLUMN,
        SUPPLIER_COLUMN,
        SEVERITY_COLUMN,
    ]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        return ["缺少必要字段：" + "、".join(missing_columns) + "，无法生成质量分析摘要。"]

    if df.empty:
        return ["当前数据为空，无法生成质量分析摘要。"]

    defect_summary = summarize_by_defect_type(df)
    part_summary = summarize_by_dimension(df, PART_NAME_COLUMN)
    process_summary = summarize_by_dimension(df, PROCESS_COLUMN)
    supplier_summary = summarize_by_dimension(df, SUPPLIER_COLUMN)
    severity_summary = summarize_by_dimension(df, SEVERITY_COLUMN)

    total_record_count = len(df)
    total_defect_count = defect_summary[DEFECT_COUNT_COLUMN].sum()
    defect_type_count = len(defect_summary)

    summary = [
        (
            f"数据总览：共 {total_record_count} 条记录，"
            f"总缺陷数量为 {total_defect_count}，涉及 {defect_type_count} 类缺陷。"
        )
    ]

    top_defect = get_top_dimension_item(defect_summary)
    if top_defect is not None:
        top_defect_count = top_defect[DEFECT_COUNT_COLUMN]
        if total_defect_count == 0:
            top_defect_ratio = 0
        else:
            top_defect_ratio = top_defect_count / total_defect_count
        summary.append(
            (
                f"主要缺陷类型：{top_defect[DEFECT_TYPE_COLUMN]} 的缺陷数量最高，"
                f"为 {top_defect_count}，占总缺陷数量的 {format_percent(top_defect_ratio)}。"
            )
        )

    top_part = get_top_dimension_item(part_summary)
    top_process = get_top_dimension_item(process_summary)
    top_supplier = get_top_dimension_item(supplier_summary)
    top_severity = get_top_dimension_item(severity_summary)

    if top_part is not None:
        summary.append(
            f"零件定位：缺陷最多的零件是 {top_part[PART_NAME_COLUMN]}，缺陷数量为 {top_part[DEFECT_COUNT_COLUMN]}。"
        )
    if top_process is not None:
        summary.append(
            f"工序定位：缺陷最多的工序是 {top_process[PROCESS_COLUMN]}，缺陷数量为 {top_process[DEFECT_COUNT_COLUMN]}。"
        )
    if top_supplier is not None:
        summary.append(
            f"供应商定位：缺陷最多的供应商是 {top_supplier[SUPPLIER_COLUMN]}，缺陷数量为 {top_supplier[DEFECT_COUNT_COLUMN]}。"
        )
    if top_severity is not None:
        summary.append(
            f"严重等级定位：缺陷最多的严重等级是 {top_severity[SEVERITY_COLUMN]}，缺陷数量为 {top_severity[DEFECT_COUNT_COLUMN]}。"
        )

    high_severity_count = df.loc[
        df[SEVERITY_COLUMN] == HIGH_SEVERITY_VALUE,
        DEFECT_COUNT_COLUMN,
    ]
    high_severity_count = pd.to_numeric(high_severity_count, errors="coerce").fillna(0).sum()
    if total_defect_count == 0:
        high_severity_ratio = 0
    else:
        high_severity_ratio = high_severity_count / total_defect_count

    if high_severity_ratio > 0.3:
        summary.append(
            (
                f"风险提示：高严重等级缺陷占比为 {format_percent(high_severity_ratio)}，"
                "占比较高，建议优先复核相关零件、工序和供应商。"
            )
        )
    else:
        summary.append(
            (
                f"风险提示：高严重等级缺陷占比为 {format_percent(high_severity_ratio)}，"
                "未超过设定阈值，但仍建议结合实际质量标准复核。"
            )
        )

    if top_defect is not None and top_process is not None and top_supplier is not None:
        summary.append(
            (
                f"后续建议：建议优先关注 {top_defect[DEFECT_TYPE_COLUMN]}、"
                f"{top_process[PROCESS_COLUMN]} 工序及 {top_supplier[SUPPLIER_COLUMN]} 的相关记录，"
                "并进行人工复核。"
            )
        )

    return summary
