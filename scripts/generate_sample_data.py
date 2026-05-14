from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "sample_data"
CSV_PATH = OUTPUT_DIR / "defect_records_sample.csv"
XLSX_PATH = OUTPUT_DIR / "defect_records_sample.xlsx"
ROW_COUNT = 100
RANDOM_SEED = 20260514

PARTS = [
    ("PT-1001", "轴套"),
    ("PT-1002", "连接板"),
    ("PT-1003", "支架"),
    ("PT-1004", "法兰盘"),
    ("PT-1005", "定位销"),
    ("PT-1006", "压盖"),
    ("PT-1007", "导轨座"),
    ("PT-1008", "密封环"),
]

PROCESSES = ["车削", "铣削", "钻孔", "热处理", "表面处理", "装配"]
DEFECT_TYPES = [
    "孔径超差",
    "表面划伤",
    "毛刺",
    "平面度超差",
    "螺纹不良",
    "尺寸偏小",
    "尺寸偏大",
]
SUPPLIERS = ["A供应商", "B供应商", "C供应商", "内部加工"]
DEPARTMENTS = ["生产部", "质量部", "工艺部", "供应链部"]
SEVERITY_LEVELS = ["低", "中", "高"]
STATUS_VALUES = ["待处理", "处理中", "已关闭"]
REMARKS = [
    "首检发现，需复核工装状态",
    "巡检发现，已隔离相关批次",
    "客户反馈复查，等待责任确认",
    "末检发现，建议调整加工参数",
    "抽检发现，需供应商提交纠正措施",
    "复检合格，记录归档",
    "返工处理中，待最终确认",
    "同批次追加抽检未见扩散",
]


def build_record(index: int, rng: random.Random, today: date) -> dict[str, object]:
    part_no, part_name = rng.choice(PARTS)
    batch_quantity = rng.choice([50, 80, 100, 120, 150, 200, 240, 300, 500])
    defect_upper_bound = max(1, min(batch_quantity, round(batch_quantity * 0.08)))
    defect_quantity = rng.randint(1, defect_upper_bound)
    defect_rate = defect_quantity / batch_quantity

    if defect_rate >= 0.05 or defect_quantity >= 15:
        severity = "高"
    elif defect_rate >= 0.02 or defect_quantity >= 5:
        severity = "中"
    else:
        severity = "低"

    return {
        "日期": (today - timedelta(days=rng.randint(0, 29))).isoformat(),
        "批次号": f"LOT-{today:%Y%m}-{index:03d}",
        "零件编号": part_no,
        "零件名称": part_name,
        "工序": rng.choice(PROCESSES),
        "缺陷类型": rng.choice(DEFECT_TYPES),
        "缺陷数量": defect_quantity,
        "批次数量": batch_quantity,
        "供应商": rng.choice(SUPPLIERS),
        "责任部门": rng.choice(DEPARTMENTS),
        "严重等级": severity,
        "处理状态": rng.choice(STATUS_VALUES),
        "备注": rng.choice(REMARKS),
    }


def generate_records(row_count: int = ROW_COUNT) -> pd.DataFrame:
    rng = random.Random(RANDOM_SEED)
    today = date.today()
    records = [build_record(index, rng, today) for index in range(1, row_count + 1)]
    return pd.DataFrame(records)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = generate_records()
    data.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    data.to_excel(XLSX_PATH, index=False, engine="openpyxl")
    print(f"Generated {len(data)} rows")
    print(CSV_PATH)
    print(XLSX_PATH)


if __name__ == "__main__":
    main()
