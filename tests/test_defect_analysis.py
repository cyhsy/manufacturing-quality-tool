import pandas as pd
import pytest

from src.defect_analysis import (
    get_top_dimension_item,
    prepare_pareto_data,
    summarize_by_defect_type,
    summarize_by_dimension,
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
    assert pareto_df.loc[len(pareto_df) - 1, "累计占比"] == pytest.approx(1)


def test_prepare_pareto_data_sorts_by_count_descending():
    df = pd.DataFrame(
        {
            "缺陷类型": ["少件", "划伤", "变形"],
            "缺陷数量": [1, 5, 3],
        }
    )

    pareto_df = prepare_pareto_data(df)

    assert list(pareto_df["缺陷类型"]) == ["划伤", "变形", "少件"]
    assert list(pareto_df["缺陷数量"]) == [5, 3, 1]


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
