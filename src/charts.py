import plotly.graph_objects as go

from src.defect_analysis import (
    CUMULATIVE_RATIO_COLUMN,
    DATE_COLUMN,
    DEFECT_COUNT_COLUMN,
    DEFECT_TYPE_COLUMN,
)


def create_pareto_chart(pareto_df):
    """Create a Pareto chart with defect counts and cumulative ratio."""
    required_columns = [
        DEFECT_TYPE_COLUMN,
        DEFECT_COUNT_COLUMN,
        CUMULATIVE_RATIO_COLUMN,
    ]
    missing_columns = [column for column in required_columns if column not in pareto_df.columns]
    if missing_columns:
        raise ValueError("Pareto 数据缺少必要字段：" + "、".join(missing_columns))

    if pareto_df.empty:
        raise ValueError("Pareto 数据为空，无法生成图表。")

    fig = go.Figure()
    fig.add_bar(
        x=pareto_df[DEFECT_TYPE_COLUMN],
        y=pareto_df[DEFECT_COUNT_COLUMN],
        name="缺陷数量",
        yaxis="y",
    )
    fig.add_scatter(
        x=pareto_df[DEFECT_TYPE_COLUMN],
        y=pareto_df[CUMULATIVE_RATIO_COLUMN],
        name="累计占比",
        yaxis="y2",
        mode="lines+markers",
    )

    fig.update_layout(
        title="缺陷类型 Pareto 图",
        xaxis_title="缺陷类型",
        yaxis=dict(title="缺陷数量"),
        yaxis2=dict(
            title="累计占比",
            overlaying="y",
            side="right",
            range=[0, 1],
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig


def create_date_trend_chart(date_summary_df):
    """Create a date trend chart with defect counts."""
    required_columns = [DATE_COLUMN, DEFECT_COUNT_COLUMN]
    missing_columns = [column for column in required_columns if column not in date_summary_df.columns]
    if missing_columns:
        raise ValueError("日期趋势数据缺少必要字段：" + "、".join(missing_columns))

    fig = go.Figure()
    if not date_summary_df.empty:
        fig.add_scatter(
            x=date_summary_df[DATE_COLUMN],
            y=date_summary_df[DEFECT_COUNT_COLUMN],
            name="缺陷数量",
            mode="lines+markers",
        )

    fig.update_layout(
        title="按日期缺陷趋势图",
        xaxis_title="日期",
        yaxis_title="缺陷数量",
    )

    return fig
