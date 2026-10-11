"""agent_tools 包：Agent 调用封装层。

分层（不要跨层）：

    agents/          Agent 决策与结构化输出
        ↓
    agent_tools/     Agent 取数封装：调 tools/ 取数 + 复用 modules/ 分析口径
        ↓
    tools/           数据访问层：读取 data/*.csv
        ↓
    data/*.csv

约定：
1. 本层**不复制** tools/ 的读表逻辑，也不直接调用 ``pandas.read_csv``；
   所有 CSV 访问必须经过 tools/ 包（可由测试校验）。
2. 质量统计一律复用 modules/ 中原有质量分析逻辑，不重写质量系统。
3. 本层不依赖 Streamlit，可被 Agent、CLI 和测试直接调用。
"""

import math
from datetime import date, datetime

import pandas as pd


def to_jsonable(value):
    """把 pandas / numpy 类型递归转换为可 JSON 序列化的原生类型。"""
    if value is None:
        return None
    if isinstance(value, (dict,)):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, int):
        return value
    if hasattr(value, "item"):  # numpy 标量 / np.datetime64
        return to_jsonable(value.item())
    return value


def df_to_records(df):
    """DataFrame -> JSON 友好的记录列表（空表返回空列表）。"""
    if df is None or df.empty:
        return []
    return to_jsonable(df.to_dict(orient="records"))
