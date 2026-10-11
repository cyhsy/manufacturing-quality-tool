# 制造质量分析工具（含「制造运营中心」工厂驾驶舱）

在原「制造质量数据分析与检验计划辅助工具」（Streamlit + 原有质量分析）基础上完成目录重构，
并新增 ERP 订单、原材料库存、设备台账、MES 生产、设备传感器五类模拟数据与
**工厂驾驶舱「制造运营中心」**页面。

> 原有质量分析功能保持不变：原质量分析逻辑整体迁移到 `modules/`，
> 页面主体逻辑仅在新的 Tab 内渲染，分析口径、字段校验与报表导出均未改动。

Sprint 2 新增 **Agent 层**：`agents/`（Supervisor + 订单 / 设备 / 质量 Agent）与
`agent_tools/`（Agent 取数封装），分层固定为
`agents/ → agent_tools/ → tools/ → data/*.csv`，详见「Agent 层」章节。

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
│   ├── inventory_analysis.py   # 库存状态口径（全项目唯一来源，页面与 Agent 共用）
│   └── production_analysis.py  # 生产（MES）分析（新增）
│
├── tools/                      # 数据访问层：只负责读取 data/ 并返回 DataFrame
│   ├── quality_tool.py         # query_quality_data()
│   ├── order_tool.py           # query_orders()
│   ├── inventory_tool.py       # query_inventory()
│   ├── equipment_tool.py       # query_equipment_status()
│   └── production_tool.py      # query_production_capacity()
│
├── agent_tools/                # Agent 取数封装层（不复制 tools，只做封装与结构化）
│   ├── order_tools.py          # 订单 + 生产能力取数（订单交付场景）
│   ├── inventory_tools.py      # 库存取数（复用 modules/inventory_analysis）
│   ├── equipment_tools.py      # 设备台账 + 传感器取数
│   └── quality_tools.py        # 质量取数（包装原有质量分析）
│
├── agents/                     # Agent 层
│   ├── supervisor_agent.py     # 总控：意图解析 -> 执行计划 -> 调度子 Agent
│   ├── order_agent.py          # 订单可交付分析（risk / reason / suggestion）
│   ├── equipment_agent.py      # 设备健康分析
│   └── quality_agent.py        # 质量分析（包装原有质量系统）
│
├── knowledge/                  # 原 RAG 知识库（知识卡 + 原始 PDF，保持原样）
├── sample_data/                # 原多场景演示数据（铸造/焊接/磨削/车削等，保持原样）
├── tests/                      # 回归测试 + 运营中心测试 + Agent 测试 + 页面冒烟测试
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

- **agents/（Agent 层）**：意图解析、执行计划与子 Agent 调度；统一输出
  `{agent, status, risk, reason, suggestion, ...}`，不直接读 CSV。
- **agent_tools/（Agent 取数封装层）**：把 `tools/` 的取数与 `modules/` 的分析口径
  封装成 Agent 友好的结构化结果，不复制 `tools/` 的读表逻辑。
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
| `order_tool.py` | `query_orders(priority, customer, product, order_id, sort_by_deadline)` | 订单信息 DataFrame |
| `inventory_tool.py` | `query_inventory(material, only_shortage)` | 当前库存 DataFrame |
| `equipment_tool.py` | `query_equipment_status(equipment_id, status, only_abnormal)` | 设备状态 DataFrame |
| `production_tool.py` | `query_production_capacity(product, process, equipment, only_running)` | 生产能力 DataFrame |
| `quality_tool.py` | `query_quality_data(process, defect_type, severity, handling_status)` | 质量异常记录 DataFrame |

筛选参数均支持单值与列表；无匹配记录时返回同结构空表。

## 分析口径要点

- **订单**：`quantity` 按数值处理；交期由 ISO 字符串解析为日期；优先级固定 `high / normal / low`（展示为 高 / 普通 / 低）。
- **库存**：`stock < safety_stock` 记为「预警」，缺口 = 安全库存 − 当前库存；
  该口径只存在于 `modules/inventory_analysis.py`，页面驾驶舱与 Agent 层共用，不存在第二套判定。
- **设备**：状态 `normal / warning / fault`，非 normal 计为异常；默认 60 天未保养记为「维保超期」。
- **生产**：`yield_rate` 兼容 `"96%"` 与 `0.96`；平均良率按在产（running）产线计算，
  避免停机产线的 0% 拉低在产良率；产能对比使用在产日产能。
- **质量**：驾驶舱直接复用原有 `modules/quality_analysis.py` + `modules/defect_analysis.py`
  的统计口径，不存在第二套质量统计逻辑。

## Agent 层（Sprint 2）

调用链（不可跨层）：

```text
agents/            意图解析、执行计划、结构化输出
    ↓
agent_tools/       取数封装：调 tools/ 取数 + 复用 modules/ 分析口径
    ↓
tools/             数据访问：读取 data/*.csv
    ↓
data/*.csv
```

### 能力注册表与执行计划

`agents/supervisor_agent.py` 用规则（可选 LLM 辅助）把用户输入解析成执行计划，
可调度能力集中在 `CAPABILITIES`：

| 能力 | 中文 | 执行 Agent | 取数模块 |
| --- | --- | --- | --- |
| `order` | 订单 | `order_agent` | `agent_tools.order_tools` |
| `inventory` | 库存 | `order_agent` | `agent_tools.inventory_tools` |
| `production` | 生产 | `order_agent` | `agent_tools.order_tools` |
| `equipment` | 设备 | `equipment_agent` | `agent_tools.equipment_tools` |
| `quality` | 质量 | `quality_agent` | `agent_tools.quality_tools` |

说明：v1 的 `agents/` 只有 order / equipment / quality 三个执行 Agent，
因此「库存」「生产」两个能力由 `order_agent` 执行（订单可交付分析本身就要用库存与产能）。
后续新增 `production_agent` 只需修改 `CAPABILITIES` 中的 `agent` 字段。

示例——`分析订单O001能否按时完成`：

```bat
python -m agents.supervisor_agent --plan-only "分析订单O001能否按时完成"
```

```text
用户输入：分析订单O001能否按时完成
意图：订单交付能力分析（order_delivery）
规划方式：rule
执行计划：
  1. [订单] order_agent -> analyze_order_delivery
  2. [库存] order_agent -> get_inventory_summary
  3. [生产] order_agent -> get_factory_capacity
```

即 Supervisor 判定需要「订单 + 库存 + 生产」三件套（`CAPABILITY_DEPENDENCIES`）：
交付能力同时取决于订单基础信息、物料齐套性与瓶颈产能。

### 运行方式

```bat
python -m agents.supervisor_agent "分析订单O001能否按时完成"    # 计划 + 调度结果
python -m agents.supervisor_agent --plan-only "设备有没有故障"  # 只看执行计划
python -m agents.supervisor_agent --llm "分析订单O001能否按时完成"  # 启用 LLM 辅助规划
python -m agents.order_agent O009        # 单订单可交付分析
python -m agents.equipment_agent         # 设备健康分析
python -m agents.quality_agent           # 质量分析
```

所有 Agent 输出都可直接 `json.dumps`（类型转换由 `agent_tools.to_jsonable()` /
`df_to_records()` 负责）。

### Agent 输出契约

每个 Agent 的 `run(capabilities, arguments)` 至少返回：

```json
{"agent": "order_agent", "status": "ok", "risk": "high", "reason": "产能不足", "suggestion": "调整排产"}
```

`agents/order_agent.py` 的订单可交付模型（v1，简单可解释）：

1. 取该产品在 MES 中各道工序的产线，逐条计算「有效日产能」：
   产线停机（`stopped`）或设备故障（`fault`）时记为 0。
2. 瓶颈产能 = 各工序有效日产能的最小值（工序串行，由最慢工序决定）；
   该产品无产线时回退全厂在产日产能，并在 `notes` 中标注。
3. 所需天数 = `ceil(订单数量 / 瓶颈产能)`。
4. 风险：关键工序不可用 → `high`；所需天数 > 交期剩余 → `high`；
   所需天数 > 0.8 × 交期剩余、或存在预警/保养设备 → `medium`；
   近交期（≤ 14 天）且存在物料预警 → 风险上调一级；其余 → `low`。

示例（焊接产线 WELD02 停机）：

```json
{
  "order_id": "O009",
  "risk": "high",
  "reason": "关键工序不可用（产线停机或设备故障）：焊接/WELD02，无法形成完整产出",
  "suggestion": "启用替代设备或外协加工，并重新排产后更新交期"
}
```

### 质量 Agent 是「包装」不是「重写」

`agents/quality_agent.py` 只调用 `agent_tools.quality_tools`，后者分别使用
`tools/quality_tool.query_quality_data()` 取数、
`modules/quality_analysis.analyze_quality_overview()` 与 `modules/defect_analysis`
做统计、`modules/root_cause_engine` 查根因。质量规则摘要直接输出原有
`generate_quality_summary()` 的结果，不做二次加工；
测试 `test_quality_agent_wraps_existing_quality_system` 断言 Agent 的
`summary_lines` 与原函数输出完全一致、`total_defects` 与原统计一致。

### LLM 辅助规划

`--llm` 时先尝试用 DeepSeek 选择能力（`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` /
`DEEPSEEK_MODEL`，与原有质量 AI 分析同一套环境变量）；未配置 Key、依赖缺失或调用失败
都会**自动回退纯规则规划**，并在 `notes` 中说明。LLM 只能从 `CAPABILITIES`
注册表里挑选能力，执行计划结构始终由本模块生成，LLM 不产出可执行步骤。

## 测试与验收

```bat
python -m pytest tests -q
```

当前结果：**116 passed**。

| 测试文件 | 覆盖内容 |
| --- | --- |
| `tests/test_app_smoke.py` | Streamlit 端到端冒烟：两个 Tab、驾驶舱四个模块与关键指标、原有质量分析功能与报表导出 |
| `tests/test_operations.py` | 新增数据字段与规模、五个查询工具、分析入口、数据一致性 |
| `tests/test_agents.py` | Agent 层：分层约束、Supervisor 计划与调度、订单交付风险、设备/质量分析与 JSON 序列化 |
| `tests/test_defect_analysis.py` 等 | 原项目质量分析回归测试（迁移后全部通过） |

```bat
python -m ruff check app.py tools modules agents agent_tools tests
```

说明：新增代码（`agents/`、`agent_tools/`、`tools/`、`modules/` 新增模块、
`tests/` 与 app.py 新增部分）ruff 无告警；仅原样迁移的
`modules/word_report_generator.py` 保留 3 处未使用导入告警，与迁移前
`src/word_report_generator.py` 完全一致（未改动原逻辑）。
