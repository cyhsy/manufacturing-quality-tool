from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = [
    "日期",
    "批次号",
    "零件编号",
    "零件名称",
    "工序",
    "缺陷类型",
    "缺陷数量",
    "批次数量",
    "供应商",
    "责任部门",
    "严重等级",
    "处理状态",
]


def load_quality_file(uploaded_file):
    """Load an uploaded quality data file into a pandas DataFrame."""
    file_name = uploaded_file.name
    suffix = Path(file_name).suffix.lower()

    if suffix == ".csv":
        try:
            return pd.read_csv(uploaded_file, encoding="utf-8-sig")
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="gbk")

    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(uploaded_file)

    raise ValueError("不支持的文件类型。请上传 csv、xlsx 或 xls 文件。")


def validate_required_columns(df):
    """Return the required columns that are missing from the DataFrame."""
    return [column for column in REQUIRED_COLUMNS if column not in df.columns]
