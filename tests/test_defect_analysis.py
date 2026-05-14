import pandas as pd
import pytest

from src.defect_analysis import summarize_by_defect_type


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
