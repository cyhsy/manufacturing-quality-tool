import pandas as pd
import pytest

from modules.defect_analysis import (
    filter_records_by_date,
    generate_quality_summary,
    get_top_defect_date,
    get_top_dimension_item,
    prepare_pareto_data,
    summarize_by_date,
    summarize_by_defect_type,
    summarize_by_dimension,
)


def build_summary_test_data():
    return pd.DataFrame(
        {
            "零件名称": ["支架", "支架", "外壳"],
            "工序": ["铣削", "铣削", "检验"],
            "缺陷类型": ["划伤", "划伤", "变形"],
            "缺陷数量": [4, 2, 1],
            "供应商": ["A供应商", "A供应商", "B供应商"],
            "严重等级": ["高", "高", "中"],
        }
    )


def test_summarize_by_defect_type_groups_counts_and_ratios():
    df = pd.DataFrame(
        {
            "缺陷类型": ["划伤", "变形", "划伤"],
            "缺陷数量": [2, 3, 4],
        }
    )

    summary = summarize_by_defect_type(df)

    assert summary.loc[0, "缺陷类型"] == "划伤"
    assert summary.loc[0, "缺陷数量"] == 6
    assert summary.loc[0, "占比"] == pytest.approx(6 / 9)
    assert summary.loc[1, "缺陷类型"] == "变形"
    assert summary.loc[1, "缺陷数量"] == 3
    assert summary.loc[1, "占比"] == pytest.approx(3 / 9)


def test_summarize_by_defect_type_sorts_by_count_descending():
    df = pd.DataFrame(
        {
            "缺陷类型": ["少件", "划伤", "变形"],
            "缺陷数量": [1, 5, 3],
        }
    )

    summary = summarize_by_defect_type(df)

    assert list(summary["缺陷类型"]) == ["划伤", "变形", "少件"]
    assert list(summary["缺陷数量"]) == [5, 3, 1]


def test_summarize_by_defect_type_raises_error_when_required_columns_missing():
    df = pd.DataFrame({"缺陷类型": ["划伤"]})

    with pytest.raises(ValueError, match="缺少必要字段：缺陷数量"):
        summarize_by_defect_type(df)


def test_summarize_by_defect_type_handles_empty_data():
    df = pd.DataFrame(columns=["缺陷类型", "缺陷数量"])

    summary = summarize_by_defect_type(df)

    assert summary.empty
    assert list(summary.columns) == ["缺陷类型", "缺陷数量", "占比"]


def test_prepare_pareto_data_includes_cumulative_ratio():
    df = pd.DataFrame(
        {
            "缺陷类型": ["划伤", "变形", "划伤", "少件"],
            "缺陷数量": [2, 3, 4, 1],
        }
    )

    pareto_df = prepare_pareto_data(df)

    assert "累计占比" in pareto_df.columns
    assert pareto_df.loc[len(pareto_df) - 1, "累计占比"] == pytest.approx(1.0)


def test_prepare_pareto_data_merges_small_counts_into_other():
    """Types with count <= 5 should be merged into '其他' as the last row."""
    df = pd.DataFrame(
        {
            "缺陷类型": ["划伤", "变形", "少件"],
            "缺陷数量": [10, 3, 1],
        }
    )

    pareto_df = prepare_pareto_data(df)

    assert list(pareto_df["缺陷类型"]) == ["划伤", "其他"]
    assert list(pareto_df["缺陷数量"]) == [10, 4]
    assert pareto_df["占比"].iloc[-1] == pytest.approx(4 / 14)
    assert pareto_df["累计占比"].iloc[-1] == pytest.approx(1.0)


def test_prepare_pareto_data_no_other_when_all_above_threshold():
    """When all types have count > 5, no '其他' row is added."""
    df = pd.DataFrame(
        {
            "缺陷类型": ["划伤", "变形"],
            "缺陷数量": [10, 8],
        }
    )

    pareto_df = prepare_pareto_data(df)

    assert "其他" not in pareto_df["缺陷类型"].values
    assert list(pareto_df["缺陷类型"]) == ["划伤", "变形"]


def test_prepare_pareto_data_all_small_becomes_other_only():
    """When all types have count <= 5, only one '其他' row exists."""
    df = pd.DataFrame(
        {
            "缺陷类型": ["划伤", "少件"],
            "缺陷数量": [3, 2],
        }
    )

    pareto_df = prepare_pareto_data(df)

    assert list(pareto_df["缺陷类型"]) == ["其他"]
    assert list(pareto_df["缺陷数量"]) == [5]
    assert pareto_df["累计占比"].iloc[-1] == pytest.approx(1.0)


def test_prepare_pareto_data_validates_last_row_100_percent():
    """The last row cumulative ratio must be exactly 100%."""
    df = pd.DataFrame(
        {
            "缺陷类型": ["A", "B"],
            "缺陷数量": [6, 3],
        }
    )

    pareto_df = prepare_pareto_data(df)
    assert pareto_df["累计占比"].iloc[-1] == pytest.approx(1.0)


def test_prepare_pareto_data_sorts_by_count_descending():
    df = pd.DataFrame(
        {
            "缺陷类型": ["少件", "划伤", "变形"],
            "缺陷数量": [1, 8, 3],
        }
    )

    pareto_df = prepare_pareto_data(df)

    assert list(pareto_df["缺陷类型"]) == ["划伤", "其他"]
    assert list(pareto_df["缺陷数量"]) == [8, 4]


def test_prepare_pareto_data_handles_empty_data():
    df = pd.DataFrame(columns=["缺陷类型", "缺陷数量"])

    pareto_df = prepare_pareto_data(df)

    assert pareto_df.empty
    assert list(pareto_df.columns) == ["缺陷类型", "缺陷数量", "占比", "累计占比"]


def test_summarize_by_dimension_groups_defect_counts():
    df = pd.DataFrame(
        {
            "零件名称": ["支架", "外壳", "支架"],
            "缺陷数量": [2, 3, 4],
        }
    )

    summary = summarize_by_dimension(df, "零件名称")

    assert summary.loc[0, "零件名称"] == "支架"
    assert summary.loc[0, "缺陷数量"] == 6
    assert summary.loc[1, "零件名称"] == "外壳"
    assert summary.loc[1, "缺陷数量"] == 3


def test_summarize_by_dimension_sorts_by_defect_count_descending():
    df = pd.DataFrame(
        {
            "工序": ["钻孔", "铣削", "检验"],
            "缺陷数量": [1, 5, 3],
        }
    )

    summary = summarize_by_dimension(df, "工序")

    assert list(summary["工序"]) == ["铣削", "检验", "钻孔"]
    assert list(summary["缺陷数量"]) == [5, 3, 1]


def test_summarize_by_dimension_includes_record_count_and_ratio():
    df = pd.DataFrame(
        {
            "供应商": ["A供应商", "B供应商", "A供应商"],
            "缺陷数量": [2, 3, 4],
        }
    )

    summary = summarize_by_dimension(df, "供应商")

    assert "记录数" in summary.columns
    assert "占比" in summary.columns
    assert summary.loc[0, "记录数"] == 2
    assert summary.loc[0, "占比"] == pytest.approx(6 / 9)


def test_summarize_by_dimension_raises_error_when_dimension_column_missing():
    df = pd.DataFrame({"缺陷数量": [1]})

    with pytest.raises(ValueError, match="缺少必要字段：严重等级"):
        summarize_by_dimension(df, "严重等级")


def test_summarize_by_dimension_handles_empty_data():
    df = pd.DataFrame(columns=["严重等级", "缺陷数量"])

    summary = summarize_by_dimension(df, "严重等级")

    assert summary.empty
    assert list(summary.columns) == ["严重等级", "缺陷数量", "记录数", "占比"]


def test_get_top_dimension_item_returns_highest_defect_count_item():
    df = pd.DataFrame(
        {
            "零件名称": ["支架", "外壳"],
            "缺陷数量": [6, 3],
            "记录数": [2, 1],
            "占比": [0.67, 0.33],
        }
    )

    top_item = get_top_dimension_item(df)

    assert top_item["零件名称"] == "支架"
    assert top_item["缺陷数量"] == 6


def test_get_top_dimension_item_returns_none_for_empty_data():
    df = pd.DataFrame(columns=["零件名称", "缺陷数量", "记录数", "占比"])

    top_item = get_top_dimension_item(df)

    assert top_item is None


def test_summarize_by_date_groups_defect_counts():
    df = pd.DataFrame(
        {
            "日期": ["2026-05-14", "2026-05-14", "2026-05-15"],
            "缺陷数量": [2, 3, 4],
        }
    )

    summary = summarize_by_date(df)

    assert summary.loc[0, "日期"] == pd.Timestamp("2026-05-14").date()
    assert summary.loc[0, "缺陷数量"] == 5
    assert summary.loc[0, "记录数"] == 2
    assert summary.loc[1, "缺陷数量"] == 4


def test_summarize_by_date_sorts_by_date_ascending():
    df = pd.DataFrame(
        {
            "日期": ["2026-05-16", "2026-05-14", "2026-05-15"],
            "缺陷数量": [1, 5, 3],
        }
    )

    summary = summarize_by_date(df)

    assert list(summary["日期"]) == [
        pd.Timestamp("2026-05-14").date(),
        pd.Timestamp("2026-05-15").date(),
        pd.Timestamp("2026-05-16").date(),
    ]


def test_get_top_defect_date_returns_highest_defect_count_date():
    date_summary = pd.DataFrame(
        {
            "日期": [
                pd.Timestamp("2026-05-14").date(),
                pd.Timestamp("2026-05-15").date(),
            ],
            "缺陷数量": [5, 8],
            "记录数": [2, 3],
        }
    )

    top_date = get_top_defect_date(date_summary)

    assert top_date["日期"] == pd.Timestamp("2026-05-15").date()
    assert top_date["缺陷数量"] == 8


def test_filter_records_by_date_returns_records_for_target_date():
    df = pd.DataFrame(
        {
            "日期": ["2026-05-14", pd.Timestamp("2026-05-14 10:00:00"), "2026-05-15"],
            "批次号": ["B001", "B002", "B003"],
            "缺陷数量": [2, 3, 4],
        }
    )

    records = filter_records_by_date(df, "2026-05-14")

    assert list(records["批次号"]) == ["B001", "B002"]


def test_date_analysis_handles_empty_data():
    df = pd.DataFrame(columns=["日期", "缺陷数量"])

    summary = summarize_by_date(df)
    top_date = get_top_defect_date(summary)
    records = filter_records_by_date(df, "2026-05-14")

    assert summary.empty
    assert list(summary.columns) == ["日期", "缺陷数量", "记录数"]
    assert top_date is None
    assert records.empty


def test_summarize_by_date_raises_clear_error_when_date_column_missing():
    df = pd.DataFrame({"缺陷数量": [1]})

    with pytest.raises(ValueError, match="缺少必要字段：日期"):
        summarize_by_date(df)


def test_filter_records_by_date_raises_clear_error_when_date_column_missing():
    df = pd.DataFrame({"缺陷数量": [1]})

    with pytest.raises(ValueError, match="缺少必要字段：日期"):
        filter_records_by_date(df, "2026-05-14")


def test_generate_quality_summary_returns_list_for_normal_data():
    df = build_summary_test_data()

    summary = generate_quality_summary(df)

    assert isinstance(summary, list)
    assert all(isinstance(item, str) for item in summary)
    assert len(summary) > 0


def test_generate_quality_summary_includes_record_and_defect_counts():
    df = build_summary_test_data()

    summary_text = "\n".join(generate_quality_summary(df))

    assert "共 3 条记录" in summary_text
    assert "总缺陷数量为 7" in summary_text


def test_generate_quality_summary_includes_top_defect_type():
    df = build_summary_test_data()

    summary_text = "\n".join(generate_quality_summary(df))

    assert "主要缺陷类型：划伤" in summary_text
    assert "为 6" in summary_text


def test_generate_quality_summary_warns_when_high_severity_ratio_over_threshold():
    df = build_summary_test_data()

    summary_text = "\n".join(generate_quality_summary(df))

    assert "高严重等级缺陷占比为 85.71%" in summary_text
    assert "占比较高，建议优先复核相关零件、工序和供应商" in summary_text


def test_generate_quality_summary_handles_empty_data():
    df = pd.DataFrame(
        columns=["缺陷类型", "缺陷数量", "零件名称", "工序", "供应商", "严重等级"]
    )

    summary = generate_quality_summary(df)

    assert summary == ["当前数据为空，无法生成质量分析摘要。"]


def test_generate_quality_summary_handles_missing_required_columns():
    df = pd.DataFrame({"缺陷类型": ["划伤"], "缺陷数量": [1]})

    summary = generate_quality_summary(df)

    assert len(summary) == 1
    assert "缺少必要字段" in summary[0]
    assert "无法生成质量分析摘要" in summary[0]
