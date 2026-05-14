from io import BytesIO

import pandas as pd

from src.report_generator import build_excel_report


EXPECTED_SHEETS = [
    "原始数据",
    "缺陷类型统计",
    "零件统计",
    "工序统计",
    "供应商统计",
    "严重等级统计",
    "质量分析摘要",
]


def build_report_test_data():
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


def test_build_excel_report_returns_non_empty_bytes_for_normal_data():
    report_bytes = build_excel_report(build_report_test_data())

    assert isinstance(report_bytes, bytes)
    assert len(report_bytes) > 0


def test_build_excel_report_can_be_read_by_pandas_excel_file():
    report_bytes = build_excel_report(build_report_test_data())

    excel_file = pd.ExcelFile(BytesIO(report_bytes))

    assert excel_file.sheet_names


def test_build_excel_report_contains_expected_sheets():
    report_bytes = build_excel_report(build_report_test_data())

    excel_file = pd.ExcelFile(BytesIO(report_bytes))

    for sheet_name in EXPECTED_SHEETS:
        assert sheet_name in excel_file.sheet_names


def test_build_excel_report_handles_empty_data():
    df = pd.DataFrame(
        columns=["零件名称", "工序", "缺陷类型", "缺陷数量", "供应商", "严重等级"]
    )

    report_bytes = build_excel_report(df)
    excel_file = pd.ExcelFile(BytesIO(report_bytes))

    assert len(report_bytes) > 0
    for sheet_name in EXPECTED_SHEETS:
        assert sheet_name in excel_file.sheet_names
