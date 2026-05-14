# 制造质量数据分析与检验计划辅助工具

## 项目简介

这是一个面向制造/质量场景的轻量级数据分析工具，用于分析质量异常记录。工具可以帮助用户识别主要缺陷、问题来源和高风险日期，并导出 Excel 分析报告。项目使用 Python、Streamlit、Pandas、Plotly 开发，并在开发过程中使用 Codex 辅助实现和迭代。

## 目标用户

- 质量工程师
- 制造工程师
- 生产现场质量管理人员
- 机械/制造相关实习岗位人员

## 解决的问题

在实际制造和质量管理工作中，质量异常记录常常分散在 Excel 表格中。人工统计缺陷类型、零件、工序和供应商比较耗时，也不容易快速判断主要问题来源。分析结果还需要整理成可汇报的报告，用于问题复盘、现场沟通或阶段性质量汇报。

## 已实现功能

- 上传 Excel/CSV 质量异常记录
- 字段完整性检查
- 原始数据预览
- 缺陷类型统计
- Pareto 图
- 多维度问题定位
- 质量分析摘要
- 日期趋势与批次追溯
- 导出 Excel 分析报告

## 使用流程

1. 启动 Streamlit 应用
2. 上传 `sample_data/defect_records_sample.xlsx` 或自己的质量异常记录
3. 查看数据预览和字段检查
4. 查看缺陷类型统计和 Pareto 图
5. 查看多维度问题定位
6. 查看质量分析摘要
7. 查看日期趋势与批次追溯
8. 下载 Excel 分析报告

## 数据字段要求

质量异常记录需要包含以下必要字段：

- 日期
- 批次号
- 零件编号
- 零件名称
- 工序
- 缺陷类型
- 缺陷数量
- 批次数量
- 供应商
- 责任部门
- 严重等级
- 处理状态

## 技术栈

- Python
- Streamlit
- Pandas
- OpenPyXL
- Plotly
- Pytest
- Git

## 本地运行方式

Windows CMD 下运行：

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m streamlit run app.py
```

也可以在 Windows 下双击 `run_app.bat` 启动项目。该脚本会自动切换到项目目录，并在存在 `.venv` 时激活本地虚拟环境。

## 展示方式

- 在线演示链接：待部署后补充
- 本地运行：可使用 `run_app.bat`，也可以使用命令行运行 `python -m streamlit run app.py`
- 推荐先查看 README 和关键功能截图，再进行现场演示
- 当前项目使用 `sample_data/defect_records_sample.xlsx` 示例数据演示

## 测试

```cmd
python -m pytest
```

## 项目边界

- 不接大模型 API
- 不做自动图纸识别
- 不做完整 QMS/MES/PLM 系统
- 不替代质量工程师判断
- 当前使用示例数据验证，真实企业数据需要进一步适配字段和规则

## AI / Codex 使用说明

- 使用 Codex 辅助完成模块拆解、代码实现、测试补充和文档迭代
- 使用 Git 保存阶段性版本
- 通过人工运行、页面检查和 pytest 测试验证功能
- 本项目不表述为 AI 自动完成项目
- 本项目不表述为熟练掌握 Agent
- 本项目不夸大为企业级系统

## 项目结构

```text
app.py
src/
tests/
sample_data/
scripts/
PROJECT_MASTER.md
TASK_BOARD.md
VERSION_SUMMARY.md
```

## 后续可扩展方向

- 接入真实企业质量记录模板
- 优化样例数据分布
- 增加更细的批次追溯分析
- 增加低配版检验计划辅助模块
- 增加更完整的报告样式
