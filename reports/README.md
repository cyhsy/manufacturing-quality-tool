# reports/ — 制造决策报告

本目录保存 `Manufacturing Supervisor` 多 Agent 协同任务
（`manufacturing_optimization`，Sprint 6）生成的 Markdown 决策报告。

## 生成方式

```bat
:: 紧张场景：计划工期超出交期 -> 给出优化措施、成本与收益
python -m agents.supervisor_agent "10000件电机壳体，15天交付，帮我优化生产方案"

:: 交付压力场景：未指定订单时自动选最紧张的在手订单
python -m agents.supervisor_agent "最近订单交付压力大，帮我优化生产方案"

:: 指定输出目录（默认 reports/）；--no-report 可只做决策不落盘
python -m agents.supervisor_agent --report-dir reports "最近订单交付压力大，帮我优化生产方案"
```

Python 侧等价入口：

```python
from agents import supervisor_agent

outcome = supervisor_agent.handle("10000件电机壳体，15天交付，帮我优化生产方案")
print(outcome["report_path"])          # reports/manufacturing_decision_电机壳体_20261011.md
print(outcome["decision_report"])      # Markdown 全文
print(outcome["decision"])             # 结构化决策（基线/措施/成本/风险/建议）
```

## 命名与覆盖规则

文件名按「订单（或产品）+ 计划基准日期」生成：

```text
manufacturing_decision_<订单编号或产品>_<YYYYMMDD>.md
```

同一输入重复运行会**覆盖**同名文件（不生成时间戳文件），因此本目录不会堆积冗余报告。

## 目录内容

| 文件 | 场景 | 结论 |
| --- | --- | --- |
| `manufacturing_decision_电机壳体_20261011.md` | 10000 件电机壳体 / 15 天交付（紧张：计划 17 天 > 交期 15 天） | 建议执行 3 项措施，预计 9 天完成，成本增加 70,200 元，净收益 3,800 元 |
| `manufacturing_decision_O001_20261011.md` | 交付压力场景（自动选中最紧张在手订单 O001） | 原计划 15 天满足交期 21 天，措施标为「可选优化」 |

## 报告结构

| 章节 | 内容 |
| --- | --- |
| 一、当前方案 | 计划工期（采购备料 + 生产）、交期剩余、是否可行、串行工期参照、排产明细 |
| 二、风险 | 订单交付 / 质量 / 设备 / 生产计划 四维风险 + 综合等级 + 提示 |
| 三、优化方案 | 逐项措施、节省天数、累计工期、对应成本；无收益的措施单列说明 |
| 四、预计 | 优化后工期、成本增加（含明细与口径）、收益、净收益 |
| 五、综合建议 | 建议等级（建议执行 / 需权衡 / 需升级 / 按原计划）、理由、行动项 |
| 六、数据来源与口径 | 每个 Agent 的取数链路与成本费率（v1 经验值） |

成本费率集中在 `modules/cost_model.py`，可按实际财务口径调整。
