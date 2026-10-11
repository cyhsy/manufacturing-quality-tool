"""agents 包：Agent 层（决策 + 结构化输出）。

组成：

- ``supervisor_agent``  总控 Agent：解析用户意图 -> 生成执行计划 -> 调度子 Agent
- ``order_agent``       订单可交付分析（订单 + 产能 + 物料）
- ``equipment_agent``   设备健康分析（设备台账 + 传感器）
- ``quality_agent``     质量分析（包装原有质量系统，不重写）

统一约定：

1. 依赖方向固定为 ``agents/`` -> ``agent_tools/`` -> ``tools/`` -> ``data/*.csv``；
   Agent 不直接读 CSV，也不直接调用 pandas 读表。
2. 每个 Agent 提供 ``run(capabilities=None, arguments=None)`` 统一入口，
   返回结构至少包含 ``{"agent", "status", "risk", "reason", "suggestion"}``。
3. 本包不导入 streamlit，可被 CLI、测试和其它程序直接调用。
"""
