# 制造质量分析工具（含「制造运营中心」工厂驾驶舱）

在原「制造质量数据分析与检验计划辅助工具」（Streamlit + 原有质量分析）基础上完成目录重构，
并新增 ERP 订单、原材料库存、设备台账、MES 生产、设备传感器五类模拟数据与
**工厂驾驶舱「制造运营中心」**页面。

> 原有质量分析功能保持不变：原质量分析逻辑整体迁移到 `modules/`，
> 页面主体逻辑仅在新的 Tab 内渲染，分析口径、字段校验与报表导出均未改动。

## 目录结构

```text
manufacturing-quality-tool/
├── app.py                      # Streamlit 入口（原有质量分析 + 新增制造运营中心 Tab）
│
├── data/                       # 模拟业务数据（新增）
│   ├── quality.csv             # 原质量数据（原 sample_data/质量异常记录样本.csv 的归一化副本）
│   ├── orders.csv              # ERP 订单模拟数据
│   ├── inventory.csv           # 原材料库存模拟数据
│   ├── equipment.csv           # 设备台账数据
│   ├── production.csv          # MES 生产数据
│   └── iot_sensor.csv          # 设备传感器数据
│
├── modules/                    # 分析层
│   ├── quality_analysis.py     # 原质量分析逻辑统一入口（原 src/data_loader.py 迁移 + 内置数据入口）
│   ├── defect_analysis.py      # 原质量分析逻辑：缺陷/维度/日期统计（原 src/defect_analysis.py）
│   ├── charts.py               # 原质量分析图表（原 src/charts.py）
│   ├── demo_data.py            # 原演示数据选择器（原 src/demo_data.py）
│   ├── root_cause_engine.py    # 原根因知识库引擎（原 src/root_cause_engine.py）
│   ├── report_generator.py     # 原 Excel 报告（原 src/report_generator.py）
│   ├── word_report_generator.py# 原 Word 8D 报告（原 src/word_report_generator.py）
│   ├── llm_quality_analysis.py # 原 DeepSeek AI 分析（原 src/llm_quality_analysis.py）
│   ├── order_analysis.py       # 订单分析（新增）
│   ├── equipment_analysis.py   # 设备分析（新增）
│   └── production_analysis.py  # 生产（MES）分析（新增）
│
├── tools/                      # 数据访问层：只负责读取 data/ 并返回 DataFrame
│   ├── quality_tool.py         # query_quality_data()
│   ├── order_tool.py           # query_orders()
│   ├── inventory_tool.py       # query_inventory()
│   ├── equipment_tool.py       # query_equipment_status()
│   └── production_tool.py      # query_production_capacity()
│
├── knowledge/                  # 原 RAG 知识库（知识卡 + 原始 PDF，保持原样）
├── sample_data/                # 原多场景演示数据（铸造/焊接/磨削/车削等，保持原样）
├── tests/                      # 回归测试 + 新增运营中心测试 + 页面冒烟测试
├── requirements.txt
├── run_app.bat
└── README.md
```

## 快速开始

```bat
py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
run_app.bat
```

等价命令：`python -m streamlit run app.py`。

打开页面后顶部有两个标签页：

| 标签页 | 内容 |
| --- | --- |
| 🏭 制造运营中心 | 工厂驾驶舱：顶部 4 个关键指标 + 订单 / 库存 / 设备 / 质量 四个模块 + MES 生产能力明细 |
| 🔍 质量分析 | 原有质量分析页面（示例数据或上传文件、帕雷托、根因、图表与 Excel/Word 报告导出） |

DeepSeek AI 分析仍按原逻辑工作：仅点击「生成 AI 质量分析」时调用，API Key 取自
`DEEPSEEK_API_KEY` 环境变量；未配置 Key 时其余统计、摘要与报表功能不受影响。

## 数据说明（data/）

| 文件 | 字段 | 规模 |
| --- | --- | --- |
| `quality.csv` | 日期、批次号、零件编号、零件名称、工序、缺陷类型、缺陷数量、批次数量、供应商、责任部门、严重等级、处理状态、备注 | 100 条记录 / 820 件缺陷 / 7 类缺陷 |
| `orders.csv` | order_id、customer、product、quantity、deadline、priority | 15 张订单 / 83,500 件 |
| `inventory.csv` | material、stock、safety_stock、unit | 13 种物料（4 种低于安全库存） |
| `equipment.csv` | equipment_id、equipment_type、status、capacity、last_maintenance | 15 台设备（正常 10 / 预警 4 / 故障 1） |
| `production.csv` | product、process、equipment、daily_capacity、yield_rate、status | 18 条产线 / 总日产能 16,450 件（在产 14,300 件） |
| `iot_sensor.csv` | timestamp、equipment_id、temperature、vibration、current、status | 30 条采集记录（6 台设备 × 5 个时刻） |

数据一致性：`production.csv.equipment` 与 `iot_sensor.csv.equipment_id` 的取值
全部存在于 `equipment.csv.equipment_id`，相关约束由测试保证。

所有 CSV 均为 UTF-8（与原有质量数据一致带 BOM，便于 Excel 直接打开）。

## 分层与迁移映射

- **tools/（数据访问层）**：只负责读取 `data/` 下的 CSV 并返回 DataFrame，路径基于项目根目录解析，
  与启动时的工作目录无关。
- **modules/（分析层）**：负责统计口径与指标计算，不直接访问 Streamlit。
- **app.py（展示层）**：只做页面渲染与展示格式转换。

原项目 `src/` → `modules/` 迁移映射：

| 原路径 | 现路径 | 迁移方式 |
| --- | --- | --- |
| `src/data_loader.py` | `modules/quality_analysis.py` | 函数签名与解析口径不变，并新增 `load_quality_dataframe()` / `analyze_quality_overview()` |
| `src/defect_analysis.py` | `modules/defect_analysis.py` | 逐字迁移，仅 `import` 前缀 `src.` → `modules.` |
| `src/charts.py` | `modules/charts.py` | 同上 |
| `src/demo_data.py` | `modules/demo_data.py` | 同上 |
| `src/root_cause_engine.py` | `modules/root_cause_engine.py` | 同上（知识库 JSON 一并迁移） |
| `src/report_generator.py` | `modules/report_generator.py` | 同上 |
| `src/word_report_generator.py` | `modules/word_report_generator.py` | 同上 |
| `src/llm_quality_analysis.py` | `modules/llm_quality_analysis.py` | 同上 |

说明：
- `tests/` 由原项目测试迁移而来（`from src.x` → `from modules.x`），
  用于证明质量分析功能未被破坏；
- `sample_data/` 原样保留：原页面「内置示例数据」下拉框需要多场景演示文件
  （铸造缺陷、焊接缺陷、磨削缺陷等），删除会破坏原有演示功能；
- `knowledge/` 为原 RAG 知识库整体迁移（知识卡 + 原始 PDF）。

## 数据读取工具（tools/）

| 工具 | 函数 | 返回 |
| --- | --- | --- |
| `order_tool.py` | `query_orders(priority, customer, product, sort_by_deadline)` | 订单信息 DataFrame |
| `inventory_tool.py` | `query_inventory(material, only_shortage)` | 当前库存 DataFrame |
| `equipment_tool.py` | `query_equipment_status(equipment_id, status, only_abnormal)` | 设备状态 DataFrame |
| `production_tool.py` | `query_production_capacity(product, process, equipment, only_running)` | 生产能力 DataFrame |
| `quality_tool.py` | `query_quality_data(process, defect_type, severity, handling_status)` | 质量异常记录 DataFrame |

筛选参数均支持单值与列表；无匹配记录时返回同结构空表。

## 分析口径要点

- **订单**：`quantity` 按数值处理；交期由 ISO 字符串解析为日期；优先级固定 `high / normal / low`（展示为 高 / 普通 / 低）。
- **库存**：`stock < safety_stock` 记为「预警」，缺口 = 安全库存 − 当前库存。
- **设备**：状态 `normal / warning / fault`，非 normal 计为异常；默认 60 天未保养记为「维保超期」。
- **生产**：`yield_rate` 兼容 `"96%"` 与 `0.96`；平均良率按在产（running）产线计算，
  避免停机产线的 0% 拉低在产良率；产能对比使用在产日产能。
- **质量**：驾驶舱直接复用原有 `modules/quality_analysis.py` + `modules/defect_analysis.py`
  的统计口径，不存在第二套质量统计逻辑。

## 测试与验收

```bat
python -m pytest tests -q
```

当前结果：**93 passed**。

| 测试文件 | 覆盖内容 |
| --- | --- |
| `tests/test_app_smoke.py` | Streamlit 端到端冒烟：两个 Tab、驾驶舱四个模块与关键指标、原有质量分析功能与报表导出 |
| `tests/test_operations.py` | 新增数据字段与规模、五个查询工具、分析入口、数据一致性 |
| `tests/test_defect_analysis.py` 等 | 原项目质量分析回归测试（迁移后全部通过） |

```bat
python -m ruff check app.py tools modules tests
```

说明：`modules/word_report_generator.py` 存在 3 处未使用导入告警，与迁移前
`src/word_report_generator.py` 完全一致（原样保留，未改动原逻辑）。
