import plotly.graph_objects as go

from modules.defect_analysis import (
    CUMULATIVE_RATIO_COLUMN,
    DATE_COLUMN,
    DEFECT_COUNT_COLUMN,
    DEFECT_TYPE_COLUMN,
    RECORD_COUNT_COLUMN,
)


def create_pareto_chart(pareto_df, highlight_indices=None):
    """Create a vertical Pareto chart: blue bars + cumulative ratio line.

    The cumulative line is aligned to the right edge of each bar.
    Bars are sorted left-to-right by count descending.

    Args:
        pareto_df: DataFrame with 缺陷类型, 缺陷数量, 累计占比 columns.
        highlight_indices: Optional set of 0-based indices to color red.
    """
    required_columns = [DEFECT_TYPE_COLUMN, DEFECT_COUNT_COLUMN, CUMULATIVE_RATIO_COLUMN]
    missing = [c for c in required_columns if c not in pareto_df.columns]
    if missing:
        raise ValueError("Pareto 数据缺少必要字段：" + "、".join(missing))

    if pareto_df.empty:
        raise ValueError("Pareto 数据为空，无法生成图表。")

    if highlight_indices is None:
        highlight_indices = set()

    n = len(pareto_df)
    total = pareto_df[DEFECT_COUNT_COLUMN].sum()
    bar_width = 0.7
    bar_x = list(range(n))
    line_x = [x + bar_width / 2 for x in bar_x]
    max_count = pareto_df[DEFECT_COUNT_COLUMN].max()

    bar_colors = [
        "#DC143C" if i in highlight_indices else "#1f77b4" for i in range(n)
    ]

    bar_ratios = pareto_df[DEFECT_COUNT_COLUMN] / total
    bar_customdata = list(
        zip(pareto_df[DEFECT_TYPE_COLUMN], bar_ratios)
    )

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=bar_x,
            y=pareto_df[DEFECT_COUNT_COLUMN],
            name="缺陷数量",
            marker_color=bar_colors,
            width=bar_width,
            text=pareto_df[DEFECT_COUNT_COLUMN],
            textposition="outside",
            textfont=dict(size=11, color="#333333"),
            hovertemplate="缺陷类型: %{customdata[0]}<br>缺陷数量: %{y}<br>占比: %{customdata[1]:.1%}<extra></extra>",
            customdata=bar_customdata,
        )
    )

    fig.add_trace(
        go.Scatter(
            x=line_x,
            y=pareto_df[CUMULATIVE_RATIO_COLUMN],
            name="累计占比",
            mode="lines+markers",
            marker=dict(color="#1f77b4", size=8, symbol="circle"),
            line=dict(color="#1f77b4", width=2),
            yaxis="y2",
            hovertemplate="缺陷类型: %{customdata}<br>累计占比: %{y:.1%}<extra></extra>",
            customdata=pareto_df[DEFECT_TYPE_COLUMN],
        )
    )

    tickangle = -45

    fig.update_layout(
        title=dict(
            text="缺陷类型帕累托图",
            x=0.5,
            xanchor="center",
            font=dict(size=16),
        ),
        xaxis=dict(
            tickvals=bar_x,
            ticktext=pareto_df[DEFECT_TYPE_COLUMN],
            tickangle=tickangle,
            showgrid=False,
            zeroline=False,
            range=[-0.5, n - 0.5],
        ),
        yaxis=dict(
            title="缺陷数量",
            range=[0, max_count * 1.12],
            showgrid=True,
            gridcolor="#E0E0E0",
            zeroline=True,
            zerolinecolor="#CCCCCC",
        ),
        yaxis2=dict(
            title="累计占比",
            range=[0, 1],
            tickformat=".0%",
            tickvals=[0, 0.2, 0.4, 0.6, 0.8, 1.0],
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        plot_bgcolor="white",
        margin=dict(t=60, b=80, l=60, r=60),
    )

    return fig


def create_root_cause_pareto_chart(root_cause_df):
    """Create a horizontal Pareto chart for root cause distribution.

    Y-axis: root cause names, top-to-bottom descending by defect count.
    Bottom X-axis: individual defect count per root cause (blue bars).
    Top X-axis: cumulative ratio 0%-100% (blue line + markers).

    Args:
        root_cause_df: DataFrame with 根因, 缺陷数量, 累计占比 columns,
                       sorted descending by 缺陷数量.
    """
    required = ["根因", "缺陷数量", "累计占比"]
    missing = [c for c in required if c not in root_cause_df.columns]
    if missing:
        raise ValueError("根因数据缺少必要字段：" + "、".join(missing))

    if root_cause_df.empty:
        raise ValueError("根因数据为空，无法生成图表。")

    n = len(root_cause_df)
    max_count = root_cause_df["缺陷数量"].max()

    # y=0 at top (largest count), y=n-1 at bottom (smallest / 其他)
    y_pos = list(range(n))
    bar_h = 0.6

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            y=y_pos,
            x=root_cause_df["缺陷数量"],
            orientation="h",
            name="缺陷数量",
            marker_color="#1f77b4",
            width=bar_h,
            text=root_cause_df["缺陷数量"],
            textposition="outside",
            textfont=dict(size=11, color="#333333"),
            hovertemplate="根因: %{customdata}<br>缺陷数量: %{x}<extra></extra>",
            customdata=root_cause_df["根因"],
        )
    )

    fig.add_trace(
        go.Scatter(
            y=y_pos,
            x=root_cause_df["累计占比"],
            name="累计占比",
            mode="lines+markers",
            marker=dict(color="#1f77b4", size=8, symbol="circle"),
            line=dict(color="#1f77b4", width=2),
            xaxis="x2",
            hovertemplate="根因: %{customdata}<br>累计占比: %{y:.1%}<extra></extra>",
            customdata=root_cause_df["根因"],
        )
    )

    fig.update_layout(
        title=dict(
            text="缺陷根因帕累托图（跨工序汇总）",
            x=0.5,
            xanchor="center",
            font=dict(size=16),
        ),
        xaxis=dict(
            title="缺陷数量",
            range=[0, max_count * 1.15],
            side="bottom",
            showgrid=True,
            gridcolor="#E0E0E0",
            zeroline=True,
            zerolinecolor="#CCCCCC",
        ),
        xaxis2=dict(
            title="累计占比",
            range=[0, 1],
            side="top",
            overlaying="x",
            tickformat=".0%",
            tickvals=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            showgrid=False,
        ),
        yaxis=dict(
            tickvals=y_pos,
            ticktext=root_cause_df["根因"],
            autorange="reversed",
            showgrid=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        plot_bgcolor="white",
        margin=dict(t=80, b=80, l=120, r=60),
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


def create_histogram(df):
    """Create a histogram of defect quantities across all records."""
    if DEFECT_COUNT_COLUMN not in df.columns:
        raise ValueError(f"缺少必要字段：{DEFECT_COUNT_COLUMN}")

    values = df[DEFECT_COUNT_COLUMN].dropna()
    if values.empty:
        raise ValueError("缺陷数量数据为空，无法生成直方图。")

    fig = go.Figure()
    fig.add_histogram(
        x=values,
        nbinsx=max(5, min(20, len(values) // 3)),
        name="缺陷数量分布",
        marker_color="#4682B4",
        hovertemplate="区间: %{x}<br>频次: %{y}",
    )
    fig.update_layout(
        title="缺陷数量直方图",
        xaxis_title="缺陷数量",
        yaxis_title="频次",
        bargap=0.05,
    )
    return fig


def create_control_chart(date_summary_df):
    """Create an Individuals control chart (I-chart) for daily defect counts.

    Uses I-MR chart methodology:
    - Center line = mean of daily defect counts
    - UCL/LCL = mean +/- 2.66 * average moving range
    """
    if date_summary_df.empty:
        raise ValueError("日期统计数据为空，无法生成控制图。")

    values = date_summary_df[DEFECT_COUNT_COLUMN].values
    dates = date_summary_df[DATE_COLUMN].values

    mean_val = values.mean()
    moving_ranges = []
    for i in range(1, len(values)):
        mr = abs(values[i] - values[i - 1])
        moving_ranges.append(mr)

    if moving_ranges:
        avg_mr = sum(moving_ranges) / len(moving_ranges)
    else:
        avg_mr = 0

    ucl = mean_val + 2.66 * avg_mr
    lcl = max(0, mean_val - 2.66 * avg_mr)

    fig = go.Figure()
    fig.add_scatter(
        x=dates,
        y=values,
        mode="lines+markers",
        name="每日缺陷数量",
        line=dict(color="#4682B4"),
    )
    fig.add_hline(
        y=mean_val,
        line_dash="dash",
        line_color="green",
        annotation_text=f"CL={mean_val:.1f}",
        annotation_position="right",
    )
    fig.add_hline(
        y=ucl,
        line_dash="dot",
        line_color="red",
        annotation_text=f"UCL={ucl:.1f}",
        annotation_position="right",
    )
    fig.add_hline(
        y=lcl,
        line_dash="dot",
        line_color="red",
        annotation_text=f"LCL={lcl:.1f}",
        annotation_position="right",
    )

    beyond_limits = [(d, v) for d, v in zip(dates, values) if v > ucl or v < lcl]
    if beyond_limits:
        beyond_dates, beyond_vals = zip(*beyond_limits)
        fig.add_scatter(
            x=beyond_dates,
            y=beyond_vals,
            mode="markers",
            name="超出控制限",
            marker=dict(color="red", size=10, symbol="x"),
        )

    fig.update_layout(
        title="每日缺陷数量控制图（I-chart）",
        xaxis_title="日期",
        yaxis_title="缺陷数量",
    )
    return fig
