import pandas as pd

from modules.quality_analysis import REQUIRED_COLUMNS, validate_required_columns


def test_validate_required_columns_returns_empty_list_when_complete():
    df = pd.DataFrame(columns=REQUIRED_COLUMNS)

    missing_columns = validate_required_columns(df)

    assert missing_columns == []


def test_validate_required_columns_returns_missing_columns():
    df = pd.DataFrame(columns=["日期", "批次号", "零件编号"])

    missing_columns = validate_required_columns(df)

    assert "零件名称" in missing_columns
    assert "处理状态" in missing_columns
    assert "日期" not in missing_columns
