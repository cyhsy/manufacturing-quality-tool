"""成本分析工具（S6-A-03）。

Agent 侧入口：把 ``modules/cost_model.py`` 的成本模型包装成可直接调用的工具，
并对结果做 JSON 友好化。

简单模型（v1 经验值，集中在 ``modules/cost_model.py`` 的常量里）：

- **加急采购成本** = 物料缺口金额 × 加急费率（默认 8%）
- **加班成本**     = 参与加班工序数 × 优化后生产工期 × 单工序日加班成本
- **换线调试成本** = 启用替代设备台数 × 单台换线成本
- **延期成本**     = 延期天数 ×（合同违约金 + 间接损失）

用法::

    from agent_tools import cost_tools

    cost_tools.expedite_purchase_cost(requirements)
    cost_tools.overtime_cost(stage_count=4, production_days=8)
    cost_tools.delay_cost(days=2)
    cost_tools.evaluate_optimization_cost(measures, ...)   # 成本增量 + 收益
"""

from agent_tools import to_jsonable
from modules import cost_model
from modules.cost_model import (  # noqa: F401 - 便于调用方直接使用模型常量与函数
    CURRENCY,
    DEFAULT_MATERIAL_PRICE,
    DELAY_INDIRECT_COST_PER_DAY,
    DELAY_PENALTY_PER_DAY,
    EQUIPMENT_SETUP_COST,
    EXPEDITE_FEE_RATE,
    MATERIAL_UNIT_PRICE,
    SHIFT_STAGE_DAILY_COST,
    delay_cost,
    equipment_setup_cost,
    evaluate_optimization_cost,
    expedite_purchase_cost,
    material_unit_price,
    overtime_cost,
    summarize_cost,
)


def estimate_optimization_cost(
    measures,
    material_requirements=None,
    optimized_production_days=None,
    baseline_delay_days=0,
    optimized_delay_days=0,
):
    """优化方案成本与收益（JSON 友好），委托 ``modules.cost_model``。"""
    return to_jsonable(
        cost_model.evaluate_optimization_cost(
            measures,
            material_requirements=material_requirements,
            optimized_production_days=optimized_production_days,
            baseline_delay_days=baseline_delay_days,
            optimized_delay_days=optimized_delay_days,
        )
    )


def get_cost_rates():
    """当前成本模型使用的费率（便于报告与审计展示）。"""
    return to_jsonable(
        {
            "currency": cost_model.CURRENCY,
            "expedite_fee_rate": cost_model.EXPEDITE_FEE_RATE,
            "shift_stage_daily_cost": cost_model.SHIFT_STAGE_DAILY_COST,
            "equipment_setup_cost": cost_model.EQUIPMENT_SETUP_COST,
            "delay_penalty_per_day": cost_model.DELAY_PENALTY_PER_DAY,
            "delay_indirect_per_day": cost_model.DELAY_INDIRECT_COST_PER_DAY,
            "material_unit_price": cost_model.MATERIAL_UNIT_PRICE,
        }
    )
