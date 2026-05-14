import pandas as pd


DEFECT_TYPE_COLUMN = "缺陷类型"
DEFECT_COUNT_COLUMN = "缺陷数量"
RATIO_COLUMN = "占比"
CUMULATIVE_RATIO_COLUMN = "累计占比"
RECORD_COUNT_COLUMN = "记录数"


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
