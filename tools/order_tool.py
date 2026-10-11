"""订单数据读取工具：ERP 模拟订单数据（data/orders.csv）。

字段口径：
    order_id  订单编号
    customer  客户
    product   产品
    quantity  数量
    deadline  交付日期（ISO 格式 YYYY-MM-DD）
    priority  优先级（high / normal / low）
"""

from tools import filter_by_values, read_data_csv


ORDER_COLUMNS = [
    "order_id",
    "customer",
    "product",
    "quantity",
    "deadline",
    "priority",
]

PRIORITY_VALUES = ("high", "normal", "low")
PRIORITY_LABELS = {"high": "高", "normal": "普通", "low": "低"}


def query_orders(priority=None, customer=None, product=None, order_id=None, sort_by_deadline=False):
    """查询订单信息。

    参数：
        priority:         优先级筛选，单值或列表，如 "high" 或 ["high", "normal"]。
        customer:         客户筛选，单值或列表。
        product:          产品筛选，单值或列表。
        order_id:         订单编号筛选，单值或列表，如 "O001"（大小写不敏感）。
        sort_by_deadline: True 时按交付日期升序（deadline 为 ISO 日期，可直接按字符串排序）。

    返回：
        pandas.DataFrame，字段与 orders.csv 一致；
        无匹配记录时返回同结构空表。
    """
    df = read_data_csv("orders.csv", ORDER_COLUMNS)

    df = filter_by_values(df, "priority", priority, case_insensitive=True)
    df = filter_by_values(df, "customer", customer)
    df = filter_by_values(df, "product", product)
    df = filter_by_values(df, "order_id", order_id, case_insensitive=True)

    if sort_by_deadline:
        df = df.sort_values("deadline", ascending=True)

    return df.reset_index(drop=True)
