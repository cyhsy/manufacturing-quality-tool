"""tools 包：制造数据读取工具。

分层约定：
- tools/*      只负责从 data/ 读取模拟业务数据并返回 DataFrame（数据访问层）。
- modules/*    负责分析口径与指标计算（分析层）。
- app.py       负责 Streamlit 展示（展示层）。

所有工具都通过 read_data_csv() 访问 data/ 目录，路径基于项目根目录解析，
因此无论从哪个工作目录启动 Streamlit 都能正确读取数据。
"""

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def read_data_csv(file_name, required_columns=None, path=None):
    """读取 data 目录下的 CSV 数据文件。

    参数：
        file_name:        data/ 下的文件名，例如 "orders.csv"。
        required_columns: 可选，必须存在的字段列表；缺失时抛出 ValueError。
        path:             可选，直接指定文件路径（用于测试或项目外数据文件）。

    返回：
        pandas.DataFrame。

    异常：
        FileNotFoundError: 数据文件不存在。
        ValueError:        文件缺少必要字段。
    """
    target = Path(path) if path is not None else DATA_DIR / file_name
    if not target.is_file():
        raise FileNotFoundError(f"数据文件不存在：{target}")

    df = pd.read_csv(target, encoding="utf-8-sig")

    if required_columns:
        missing_columns = [column for column in required_columns if column not in df.columns]
        if missing_columns:
            raise ValueError(
                f"{file_name} 缺少必要字段：" + "、".join(missing_columns)
            )

    return df


def _as_filter_set(value):
    """把 None / 标量 / 序列统一成集合，便于对同一字段做多值筛选。"""
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return {value}
    return set(value)


def filter_by_values(df, column, value, case_insensitive=False):
    """按单值或多值筛选 DataFrame；value 为 None 时不筛选。

    参数：
        df:               待筛选的 DataFrame。
        column:           用于筛选的字段名。
        value:            单值或值序列（list/tuple/set）。
        case_insensitive: 为 True 时忽略大小写（用于状态、优先级等英文枚举值）。
    """
    values = _as_filter_set(value)
    if values is None:
        return df

    if case_insensitive:
        values = {str(item).lower() for item in values}
        mask = df[column].astype(str).str.lower().isin(values)
    else:
        mask = df[column].isin(values)

    return df.loc[mask]
