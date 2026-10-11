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
│   ├── iot_sensor.csv          # 设备传感器数据
│   ├── product_mapping.csv     # 产品映射层：MES 产品 -> 质量零件（S4.1-A-02）
│   ├── bom.csv                 # 物料用量（S5-A-02，用于按订单计算物料需求）
│   └── work_orders.csv         # 维修工单（S3-A-03，调用 create_work_order() 时追加）
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
│   ├── equipment_knowledge.py  # 设备故障知识库检索（knowledge/equipment/，S3-A-01/02）
│   ├── quality_knowledge.py    # 质量改善知识库检索（knowledge/quality/，S4-A-03）
│   ├── quality_issue_analysis.py # 质量议题趋势口径（S4-A-01）
│   ├── planning_engine.py      # 排产规则模型（S5-A-03）
│   ├── knowledge_base.py       # 知识库 Markdown 解析公共工具
│   └── production_analysis.py  # 生产（MES）分析（新增）
│
├── tools/                      # 数据访问层：只负责读取 data/ 并返回 DataFrame
│   ├── quality_tool.py         # query_quality_data()
│   ├── order_tool.py           # query_orders()
│   ├── inventory_tool.py       # query_inventory()
│   ├── equipment_tool.py       # query_equipment_status()
│   ├── iot_sensor_tool.py      # query_sensor_readings() / query_latest_sensor_reading()
│   ├── traceability_tool.py    # query_traceability() 质量追溯（S4-A-02）
│   └── production_tool.py      # query_production_capacity()
│
├── agent_tools/                # Agent 取数封装层（不复制 tools，只做封装与结构化）
│   ├── order_tools.py          # 订单 + 生产能力取数（订单交付场景）
│   ├── inventory_tools.py      # 库存取数（复用 modules/inventory_analysis）
│   ├── equipment_tools.py      # 设备台账 + 传感器 + 故障知识库取数
│   ├── work_order_tools.py     # create_work_order() 维修工单（S3-A-03）
│   ├── planning_tools.py       # generate_production_plan() 生产计划（S5-A-02）
│   └── quality_tools.py        # 质量取数（包装原有质量分析）
│
├── agents/                     # Agent 层
│   ├── supervisor_agent.py     # 总控：意图解析 -> 执行计划 -> 调度子 Agent
│   ├── order_agent.py          # 订单可交付分析（risk / reason / suggestion）
│   ├── equipment_agent.py      # 设备异常检测 + 故障诊断 + 维修工单（S3-A-02）
│   ├── planning_agent.py       # 生产计划编排（S5-A-01）
│   └── quality_agent.py        # 质量分析（包装原有质量系统）
│
├── knowledge/                  # 原 RAG 知识库（知识卡 + 原始 PDF，保持原样）
│   ├── equipment/              # 设备故障案例库（24 条，S3-A-01）
│   └── quality/                # 质量改善案例库（24 条 / 4 类，S4-A-03）
├── sample_data/                # 原多场景演示数据（铸造/焊接/磨削/车削等，保持原样）
├── tests/                      # 回归 + 运营中心 + Agent + 设备诊断 + 质量议题测试
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
| `product_mapping.csv` | mes_product、quality_part、mapping_reason | 13 条映射，覆盖 12 个 MES 产品与 8 个质量零件 |
| `bom.csv` | product、material、unit_usage、unit | 13 条物料用量，覆盖全部 12 个 MES 产品 |
| `work_orders.csv` | 维修编号、设备、故障、优先级、负责人、建议时间、创建时间、状态、来源、依据 | 2 条示例工单；调用 `create_work_order()` 时按天递增追加 |

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
| `quality_issue_analysis` | 质量议题 | `quality_agent` | `agent_tools.quality_tools` + `tools/traceability_tool.py` |
| `production_planning` | 生产计划 | `planning_agent` | `agent_tools.planning_tools`（-> `modules/planning_engine.py`） |
| `equipment_failure` | 设备故障 | `equipment_agent` | `agent_tools.equipment_tools` + `agent_tools.work_order_tools` |

说明：`CAPABILITY_ORDER`（五维：订单/库存/生产/设备/质量）用于「综合风险」与「运营总览」；
`equipment_failure`（S3-A-04）与 `quality_issue_analysis`（S4-A-04）是**动作能力**，
只在用户指向具体设备或具体质量议题时启用，不参与五维扩张，
避免综合风险报告被单台设备诊断或单个质量议题替换。

说明：v1 的 `agents/` 只有 order / equipment / quality 三个执行 Agent，
因此「库存」「生产」两个能力由 `order_agent` 执行（订单可交付分析本身就要用库存与产能）。
后续新增 `production_agent` 只需修改 `CAPABILITIES` 中的 `agent` 字段。

### 意图规则与实体抽取

Supervisor 不是「关键词直连工具」，而是先判定意图、再决定能力集合（`INTENT_RULES`），
并同时抽取实体（订单编号 / 产品 / 数量 / 交期天数或日期）：

| 意图 | 触发 | 能力集合 |
| --- | --- | --- |
| `comprehensive_risk` | 风险、隐患、有没有问题、出问题 | **全部 5 维**（订单+库存+生产+设备+质量） |
| `order_delivery` | 能否、按时、交付、交期、完成、拖期 | 订单+库存+生产 |
| `equipment_failure` | 报警、告警、故障、停机、异常、诊断、维修 + **具体设备编号** | 设备故障（单台设备诊断 + 维修工单） |
| `quality_issue_analysis` | 质量下降、质量变差、质量趋势、不良上升、缺陷率、客诉，或**「质量域词 + 趋势词」组合**（良率下降、合格率下滑、尺寸异常） | 质量议题（趋势 + 追溯 + 改善建议） |
| `production_planning` | 生产计划、生产方案、**排产**、怎么安排生产、如何安排生产、交付计划 | 生产计划（排产 + 风险 + 建议） |
| `overview` | 什么情况、整体情况、概况、总览 | 全部 5 维 |
| 细分意图 | 仅命中单一维度关键词（设备/质量/库存/生产/订单） | 该维度 |
| `mixed_query` | 同时命中多个维度 | 命中维度 |
| 兜底 | 仅给出订单号或「产品+数量」 | 订单+库存+生产 |

要点：

- **风险类问题走五维综合风险**：验收要求风险问答输出「质量风险」「设备风险」，
  只有真正调用 `quality_agent` / `equipment_agent` 才可能产出这两段，
  因此风险意图强制覆盖全部 5 个能力（任务书 S2-A-03 的原示例不含「风险」字样，
  仍严格保持订单+库存+生产三件套）。
- **组合条件判定（S4.1-A-01）**：质量议题意图支持 `keyword_groups`，
  即「质量域词（质量/良率/合格率/缺陷/不良/毛刺/尺寸/划伤/超差/返工/报废/客诉/投诉）
  + 趋势词（下降/下滑/变差/恶化/走低/降低/上升/升高/超标/异常/波动）」**同时命中**，
  因此「最近电机壳体良率下降，分析原因」能正确落到 `quality_issue_analysis`，
  而「看看质量缺陷情况」仍走质量总览（无趋势词）。
- **口述订单也能算**：`extract_entities()` 支持
  `10000件` / `15天` / `2周` / `2026-11-10` / `O001` 等写法，
  没有订单编号时按用户给出的产品、数量、交期单独测算，并与在手订单做交叉引用。
- **设备编号与订单编号分离**：订单号只保留台账中真实存在的 `O001` 形式，
  设备号按 `[A-Z]{2,}\d{2,}` 与设备台账比对（`CNC02` 不会被误判成订单号）。

### 执行计划示例

示例 1——任务书原示例（三件套）：

```bat
python -m agents.supervisor_agent --plan-only --no-llm "分析订单O001能否按时完成"
```

```text
意图：订单交付能力分析（order_delivery）
执行计划：
  1. [订单] order_agent -> analyze_order_delivery
  2. [库存] order_agent -> get_inventory_summary
  3. [生产] order_agent -> get_factory_capacity
```

示例 2——口述订单 + 风险问答（五维）：

```bat
python -m agents.supervisor_agent --plan-only --no-llm "工厂收到10000件电机壳体订单，15天交付，帮我分析风险"
```

```text
意图：工厂综合风险分析（comprehensive_risk）
识别实体：product=电机壳体、quantity=10000、delivery_days=15
执行计划：
  1. [订单] order_agent -> analyze_order_request
  2. [库存] order_agent -> get_inventory_summary
  3. [生产] order_agent -> get_factory_capacity
  4. [设备] equipment_agent -> analyze_equipment_status
  5. [质量] quality_agent -> analyze_quality
```

### 运行方式

```bat
python -m agents.supervisor_agent "分析订单O001能否按时完成"              # 计划 + 调度结果
python -m agents.supervisor_agent --plan-only "设备有没有故障"            # 只看执行计划
python -m agents.supervisor_agent --no-llm "帮我分析风险"                # 强制纯规则规划
python -m agents.supervisor_agent --llm "帮我分析风险"                   # 强制启用 LLM 规划
python -m agents.supervisor_agent "工厂收到10000件电机壳体订单，15天交付，帮我分析风险"
python -m agents.order_agent O009                                        # 按订单编号分析
python -m agents.order_agent --product 电机壳体 --quantity 10000 --days 15  # 按口述订单分析
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

Supervisor 在 `handle()` 中额外产出**分段风险报告**，分段标题固定：

| capability | 分段标题 |
| --- | --- |
| `order` | 订单交付风险 |
| `inventory` | 物料库存风险 |
| `production` | 产能风险 |
| `equipment` | 设备风险 |
| `quality` | 质量风险 |

`overall_risk` 取各段最高风险。风险类问题下「质量风险」「设备风险」两段必然出现（实测节选）：

```json
{
  "overall_risk": "high",
  "sections": [
    {"capability": "order", "title": "订单交付风险", "risk": "medium",
     "reason": "产能可满足：瓶颈日产能 800 件，完成 10000 件约需 13 天，交期剩余 15 天；交期较紧",
     "suggestion": "优先排产并预留缓冲时间", "order_source": "user_description", "order_id": null},
    {"capability": "equipment", "title": "设备风险", "risk": "high",
     "reason": "设备 15 台，正常 10 台，异常 5 台（预警 4、故障 1）；故障设备：WELD02，相关工序产能为 0",
     "suggestion": "优先安排维保超期设备保养后再排产"},
    {"capability": "quality", "title": "质量风险", "risk": "high",
     "reason": "共 820 件缺陷，涉及 7 类缺陷；主要缺陷类型为 尺寸偏小（占比 19.5%）；高严重等级缺陷占比 77.1%",
     "suggestion": "高严重等级缺陷占比偏高，建议立即组织人工复核并追溯责任工序"}
  ]
}
```

`agents/order_agent.py` 的订单可交付模型（v1，简单可解释），
两个入口（ERP 在手订单 / 用户口述订单）共用同一套测算：

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

```text
意图：设备故障诊断（equipment_failure）
识别实体：设备编号=CNC02
执行计划：
  1. [设备故障] equipment_agent -> diagnose_equipment_failure
```

### 设备 Agent：异常检测 → 故障诊断 → 维修工单（Sprint 3）

三级升级：**异常检测**（车队级）→ **故障诊断**（单台）→ **维修工单生成**。

```bat
python -m agents.equipment_agent                       # 车队设备健康总览
python -m agents.equipment_agent CNC02                 # 单台设备故障诊断
python -m agents.equipment_agent CNC02 --work-order     # 诊断并落库维修工单
python -m agents.equipment_agent CNC02 --temperature 95 --vibration 6.2
python -m agents.supervisor_agent "CNC02报警了，帮我分析"   # Supervisor 自动路由到设备 Agent
```

**1）设备故障知识库（S3-A-01）**：`knowledge/equipment/` 共 24 条案例，
每条为「现象 / 可能原因 / 处理 / 适用设备 / 关联信号 / 优先级」，例如 `主轴温升异常.md`。
检索在 `modules/equipment_knowledge.py`，打分规则固定且可解释：

| 命中项 | 权重 |
| --- | --- |
| 数值条件命中（如 `温度>90℃` 且实测 95℃） | +3.0 |
| 关联信号命中 | +1.5 |
| 适用设备类型命中 | +1.5 |

置信度 = `min(0.95, 总分/7)`；低于 3.0 分不视为匹配；排序固定为
（总分降序、数值条件命中数降序、高优先级优先、案例编号升序），结果可复现。
**只有异常设备参与信号匹配**，正常设备不会命中任何案例。
置信度表示「与知识库案例的相似度」，不是工程失效概率或放行判定。

**2）诊断输出（S3-A-02）**：`diagnose_equipment()` 直接返回任务书约定结构：

```json
{
  "equipment": "CNC02",
  "status": "abnormal",
  "fault": "轴承磨损",
  "confidence": 0.95,
  "recommendation": ["检测轴承间隙", "更换轴承", "复核装配预紧"],
  "possible_causes": ["长期疲劳磨损", "润滑不良", "装配预紧不当"],
  "evidence": ["设备台账状态：warning", "振动=6.2", "振动>3.5 命中（实测 6.2）", "..."],
  "work_order": {"维修编号": "WO-20261011-001", "优先级": "高", "负责人": "机加维修组", "...": "..."}
}
```

异常检测口径：台账 `warning/fault`、传感器 `warning/alarm`、产线
`stopped/maintenance`、或显式报警，任一命中即 `status=abnormal`；
无台账与传感器数据时为 `unknown`（不误判为正常）。
`run()` 在多 Agent 场景保持统一信封（`status` 为执行状态），
诊断结果放在 `diagnosis` 字段，并把 `fault`/`confidence`/`recommendation`/`equipment` 提升到顶层。

**3）维修工单（S3-A-03）**：`agent_tools/work_order_tools.create_work_order()` 生成
**维修编号 / 设备 / 故障 / 优先级 / 负责人 / 建议时间**（另含创建时间/状态/来源/依据）：

| 字段 | 生成规则 |
| --- | --- |
| 维修编号 | `WO-YYYYMMDD-NNN`，按当天已有工单递增，跨天从 001 重新开始 |
| 优先级 | 显式指定 > 设备状态（fault→紧急、warning→高） > 诊断置信度 ≥0.8→高 > 普通 |
| 负责人 | 显式指定 > 按设备类型分配班组（CNC/MILLING/DRILLING→机加维修组 等） |
| 建议时间 | 创建时间 + 响应时限（紧急 4h / 高 24h / 普通 72h） |

默认落库到 `data/work_orders.csv`（`persist=True`）；Agent 分析默认只生成草稿
（`persist=False`，保持只读），CLI 加 `--work-order` 才落库。

### 生产计划 Agent（Sprint 5）

把「订单 → 产能 → 故障设备 → 库存 → 质量」串成可执行排产方案。

```bat
python -m agents.planning_agent                                        # 最紧急在手订单
python -m agents.planning_agent O009
python -m agents.planning_agent --product 电机壳体 --quantity 10000 --days 15 --today 2026-10-11
python -m agents.supervisor_agent "这个订单怎么安排生产？"
python -m agents.supervisor_agent "10000件电机壳体，15天交付，怎么安排生产"
```

**1）规则模型（S5-A-03，`modules/planning_engine.py`，第一版不做优化算法）**

| 规则 | 落地方式 |
| --- | --- |
| 1 优先满足交期 | 按流水（相邻工序重叠，流转 1 天）估工期，超交期即给压缩方案 |
| 2 避开故障设备 | 停机/故障产线**自动替换**为同工序可用设备；无替代则判为 blocked |
| 3 优先高风险订单 | 优先级 high 的订单采购按**加急 1 天**（常规 3 天）并提示预留缓冲 |
| 4 考虑库存 | 按 `bom.csv` 算本单物料需求，缺料时在计划最前面插入采购备料阶段 |

工期口径（可复现）：`d_i = ceil(数量 / 有效日产能_i)`，
`生产工期 = max_i(流转偏移_i + d_i)`，`总工期 = 采购备料天数 + 生产工期`，
并同时给出**串行上限** `serial_days = Σ d_i` 作参照。
「有效日产能」与订单 Agent 共用 `evaluate_effective_capacity()` —— 停机/故障记 0，瓶颈取工序最小值。

**2）实测输出（Sprint 5 场景：10000 件电机壳体，15 天交付）**

```text
risk: high   plan_status: tight
reason: 计划总工期 17 天（采购备料 3 天 + 生产 14 天）；交期剩余 15 天，超出 2 天；
        瓶颈工序 CNC加工（CNC01，800 件/天）；物料缺口：铝合金；设备风险 high；质量风险 high

生产方案：
  Day1-3：采购备料（铝合金）（铝合金缺口 20000kg；常规采购 3 天）
  Day4-13：铸造（CAST01，1000 件/天，需 10 天）
  Day5-17：CNC加工（CNC01，800 件/天，需 13 天）
  Day6-12：装配（ASSY01，1500 件/天，需 7 天）
  Day7-11：检测（TEST01，2000 件/天，需 5 天）

风险：
  [medium] CNC加工 工序备用设备 CNC02 停机或故障 -> 扩产时不可用（日产能 600 件）
  [high]   铝合金 缺口 20000kg                   -> 开工前必须到料，否则计划整体顺延
  [high]   计划工期 17 天 > 交期剩余 15 天          -> 超出 2 天，无法满足交期
  [info]   瓶颈工序：CNC加工（CNC01，800 件/天）    -> 决定整体产出节奏

建议：
  - 启用 CNC加工 的替代/并行设备：CNC03（850 件/天），瓶颈产能 800 → 1650 件/天，启用后生产工期 10 天
  - 将采购改为加急（3 天 → 1 天，可省 2 天）：铝合金
  - 关键工序增加班次，产能约提升 30%（生产工期可降至 8 天）
  - 按上述措施执行后总工期 11 天，可满足交期 15 天
```

故障设备替换实测（规则 2）：`O002`（变速箱壳体）的 CNC 工序原设备 CNC02 停机，
计划自动改用 CNC03（850 件/天），风险从 high 降为 medium：

```text
Day5-10：CNC加工（CNC03，850 件/天，需 6 天；原设备 CNC02 停机或故障，改用替代设备 CNC03（850 件/天））
```

**3）调用关系（S5-A-01）**：`agents.planning_agent`

```text
agents.order_agent          -> 交付能力基准（delivery_baseline）
agent_tools.inventory_tools -> 库存风险（inventory_risk）
agent_tools.order_tools     -> 当前产能（-> tools.production_tool）
agents.equipment_agent      -> 设备风险（equipment_risk）
agents.quality_agent        -> 在制质量风险（quality_risk，可用 include_quality=False 关闭）
agent_tools.planning_tools  -> 排产（generate_production_plan -> modules/planning_engine）
```

未指定订单时自动取**最紧急在手订单**（高优先级优先、交期最早优先），
并在 `assumptions` 中显式说明；只给产品缺数量时会要求补齐，而不是静默改用其它订单。

### 质量 Agent 是「包装」不是「重写」

`agents/quality_agent.py` 只调用 `agent_tools.quality_tools`，后者分别使用
`tools/quality_tool.query_quality_data()` 取数、
`modules/quality_analysis.analyze_quality_overview()` 与 `modules/defect_analysis`
做统计、`modules/root_cause_engine` 查根因。质量规则摘要直接输出原有
`generate_quality_summary()` 的结果，不做二次加工；
测试 `test_quality_agent_wraps_existing_quality_system` 断言 Agent 的
`summary_lines` 与原函数输出完全一致、`total_defects` 与原统计一致。

### 质量议题分析（Sprint 4）

在原有质量总览之上新增二级能力 `quality_issue_analysis`：按 **产品 / 缺陷 / 时间** 定位问题，
串起「趋势 → 追溯 → 改善」三步。

```bat
python -m agents.quality_agent --issue                        # 质量议题分析（默认窗口）
python -m agents.quality_agent --issue --defect 尺寸偏大
python -m agents.quality_agent --issue --product 支架 --process 铣削 --batch LOT-202605-001
python -m agents.quality_agent --issue --product 电机壳体       # MES 产品经产品映射落到质量零件
python -m agents.quality_agent --issue --start 2026-05-01 --end 2026-05-14
python -m agents.supervisor_agent "最近质量下降，帮我分析"        # Supervisor 自动路由
python -m agents.supervisor_agent "最近电机壳体良率下降，分析原因"   # S4.1 验收输入
```

**1）趋势口径（`modules/quality_issue_analysis.py`）**：
以数据中**最新日期**为基准（不用系统当天，避免数据滞后导致窗口为空），
默认窗口 = 可用数据跨度的一半（本数据集为 15 天），对比紧邻的等长上期；
指标用**缺陷率 = 缺陷数量合计 / 批次数量合计**，避免只看绝对数量被产量干扰。

**2）产品映射层（S4.1-A-02，`data/product_mapping.csv`）**：
建立 **MES 产品 → 质量零件** 的映射（13 条，覆盖 12 个 MES 产品与 8 个质量零件），
因为 `quality.csv` 的「零件名称」与 MES「产品」**没有交集**，不经映射无法互相查询。
解析顺序：查询对象本身即质量零件 → 直接匹配；否则查映射表；都不是则退回包含匹配。
`query_traceability()` 输出：

```json
{
  "original_product": "电机壳体",
  "mapped_quality_parts": ["支架", "法兰盘"],
  "mapping_source": "product_mapping.csv",
  "mapping_reason": "MES产品质量由关键零件表征；电机壳体端面配合由法兰盘表征"
}
```

**3）质量追溯（S4-A-02 / S4.1-A-03）**：
MES 产品 → 产品映射 → 质量对象 → 缺陷 → 工序 → 设备 → 生产记录。
跨系统关联以**工序**为纽带（含 `钻孔→钻削`、`铣削→CNC加工` 的工序标准化），
MES 中无对应产线的工序（如「表面处理」）在 `unmatched_processes` 中**显式列出，不静默丢弃**；
`iot_sensor.csv` 只覆盖部分设备，未装传感器的设备其 `最新传感器` 为 `None`。

**4）改善知识库（S4-A-03，`knowledge/quality/`）**：24 条案例，覆盖
**尺寸异常 / 表面缺陷 / 铸造缺陷 / 装配异常** 各 6 条，每条含
**现象 / 原因 / 验证方法 / 改善措施**，并与数据集里的 7 类真实缺陷对齐。
检索打分：关联缺陷 +3.0、适用工序 +2.0、类别 +1.5，
置信度 = `min(0.95, 总分/6)`，低于 3.0 分（缺陷未命中）不算匹配。

**5）订单关联（S4.1-A-04）**：质量异常 → 生产设备 → 影响产品 → 订单风险。
取数走 `agent_tools.order_tools.get_orders()`（→ `tools.order_tool.query_orders()`），
交付风险复用 `agents.order_agent.evaluate_delivery()` 的判定口径，不新增第二套订单风险模型。

```text
影响订单：O002、O013、O001、O006、O004（共 9 张，交付风险 high，综合风险 high）
primary_products:   主轴法兰 / 减速器壳体 / 涡轮支架 / 电机壳体   ← 经产品映射反向直接定位
equipment_products: 变速箱壳体 / 不锈钢接头 / 销轴 / 传感器外壳   ← 共享设备（潜在影响）
relation:           直接映射 / 共享设备（逐单标注）
```

- 每条订单带 `order_id` / `customer` / `product` / `quantity` / `deadline` / `risk` / `reason` / `relation`，
  按风险严重度排序；
- `delivery_risk` 取受影响订单的最严重等级；`combined_risk` = max(质量风险, 交付风险)。

实测输出示例（`python -m agents.quality_agent --issue`）：

```text
risk: medium        verdict: 持平（缺陷率 4.000% → 3.996%，环比 -0.1%）
本期：49 条记录 / 398 件缺陷 / 缺陷率 3.996%；主要缺陷 尺寸偏大，主要工序 铣削
环比恶化维度：尺寸偏大（38→102 件）、毛刺（47→87 件）、热处理（21→68 件）
改善建议：尺寸偏大→QI-001（匹配度 0.83）按刀具寿命强制换刀 / 加工前预热主轴
          毛刺→QI-008    孔径超差→QI-003
```

注意：该数据集整体缺陷率**环比持平**，所以分析如实给出「持平」，
同时指出具体恶化的缺陷类型与工序 —— 不为迎合"质量下降"的提问而编造趋势。

### LLM 规划（默认优先、规则兜底）

`build_plan(use_llm=None)` 为默认行为：**配置了 `DEEPSEEK_API_KEY` 就用 LLM 规划，否则用规则**；
`--llm` / `--no-llm` 可强制开关。环境变量与原有质量 AI 分析同一套：
`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`。

安全与稳健性：

- LLM 只能从 `CAPABILITIES` 注册表里挑能力，越权能力（例如 `delete_database`）直接丢弃；
- LLM 与规则结果**取并集**，只能增补不能削减 —— 避免 LLM 漏选导致「质量风险 / 设备风险」缺失；
- 未配置 Key、依赖缺失、调用失败、返回非 JSON、未选出合法能力，任一情况都回退纯规则规划，
  并在 `notes` 中说明；
- 执行计划结构始终由本模块生成，LLM 不产出可执行步骤本身。

以上路径均有测试覆盖（通过注入假客户端验证，测试过程不发起真实网络请求）：
`test_llm_planner_is_used_by_default_when_key_present`、
`test_llm_planner_drops_unregistered_capabilities`、
`test_llm_planner_cannot_remove_rule_capabilities`、
`test_llm_invalid_response_falls_back_to_rules`、
`test_no_llm_switch_forces_rules_even_with_key`、
`test_llm_planner_without_key_never_calls_client`。

## 测试与验收

```bat
python -m pytest tests -q
```

当前结果：**219 passed**。

| 测试文件 | 覆盖内容 |
| --- | --- |
| `tests/test_app_smoke.py` | Streamlit 端到端冒烟：两个 Tab、驾驶舱四个模块与关键指标、原有质量分析功能与报表导出 |
| `tests/test_operations.py` | 新增数据字段与规模、五个查询工具、分析入口、数据一致性 |
| `tests/test_agents.py` | Agent 层：分层约束、意图与实体抽取、五维风险覆盖、订单交付风险（含口述订单）、LLM 规划路径、JSON 序列化 |
| `tests/test_equipment_diagnosis.py` | S3-A：设备知识库（≥20 条）、传感器工具、故障诊断契约、维修工单生成规则、Supervisor 设备故障路由 |
| `tests/test_quality_issue.py` | S4-A：质量改善知识库（≥20 条 / 4 类）、质量追溯链路、议题趋势与改善建议、Supervisor 质量议题路由 |
| `tests/test_quality_mapping.py` | S4.1：良率下降等组合说法的意图优先级、产品映射层、追溯映射字段、质量异常→订单交付风险 |
| `tests/test_production_planning.py` | S5-A：四条排产规则、故障设备替换、物料缺口、日级方案、Planning Agent 取数来源、Supervisor 排产路由 |
| `tests/test_defect_analysis.py` 等 | 原项目质量分析回归测试（迁移后全部通过） |

```bat
python -m ruff check app.py tools modules agents agent_tools tests
```

说明：新增代码（`agents/`、`agent_tools/`、`tools/`、`modules/` 新增模块、
`tests/` 与 app.py 新增部分）ruff 无告警；仅原样迁移的
`modules/word_report_generator.py` 保留 3 处未使用导入告警，与迁移前
`src/word_report_generator.py` 完全一致（未改动原逻辑）。
