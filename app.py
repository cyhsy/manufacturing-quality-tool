import hashlib
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from modules import equipment_analysis, order_analysis, production_analysis
from modules.charts import (
    create_control_chart,
    create_date_trend_chart,
    create_histogram,
    create_pareto_chart,
    create_root_cause_pareto_chart,
)
from modules.defect_analysis import (
    DATE_COLUMN,
    DEFECT_COUNT_COLUMN,
    filter_records_by_date,
    generate_quality_summary,
    get_top_defect_date,
    get_top_dimension_item,
    prepare_pareto_data,
    summarize_by_date,
    summarize_by_defect_type,
    summarize_by_dimension,
)
from modules.demo_data import list_sample_files, load_sample_upload
from modules.llm_quality_analysis import (
    DeepSeekAnalysisError,
    generate_deepseek_quality_analysis,
)
from modules.quality_analysis import (
    analyze_quality_overview,
    load_quality_file,
    validate_required_columns,
)
from modules.report_generator import build_excel_report
from modules.root_cause_engine import (
    find_defect_root_causes,
    get_all_process_types,
    get_defect_types_for_process,
    get_root_causes,
    probability_to_level,
)
from modules.word_report_generator import build_word_report
from tools import read_data_csv
from tools.equipment_tool import query_equipment_status
from tools.inventory_tool import query_inventory
from tools.order_tool import query_orders
from tools.production_tool import query_production_capacity


def _style_df(df, percent_cols=None):
    """Apply center text alignment and optional percentage formatting."""
    styled = df.style.set_properties(**{"text-align": "center"})
    if percent_cols:
        fmt = {c: "{:.1%}" for c in percent_cols if c in df.columns}
        if fmt:
            styled = styled.format(fmt)
    return styled


def show_dimension_analysis(df, dimension_col, item_label):
    try:
        summary = summarize_by_dimension(df, dimension_col)
    except ValueError as exc:
        st.warning(str(exc))
        return

    top_item = get_top_dimension_item(summary)
    if top_item is None:
        st.warning(f"暂无可用于按{dimension_col}统计的数据。")
    else:
        st.write(
            f"缺陷最多的{item_label}：{top_item[dimension_col]}，"
            f"缺陷数量：{top_item['缺陷数量']}"
        )

    st.dataframe(_style_df(summary.head(10), ["占比"]), width="stretch")


def show_date_trend_and_trace(df):
    st.subheader("日期趋势与批次追溯")
    try:
        date_summary = summarize_by_date(df)
        if date_summary.empty:
            st.info("暂无可用于生成日期趋势与批次追溯的数据。")
            return

        date_trend_chart = create_date_trend_chart(date_summary)
        st.plotly_chart(date_trend_chart, width="stretch", config={"displayModeBar": False})

        top_defect_date = get_top_defect_date(date_summary)
        if top_defect_date is not None:
            st.write(
                f"缺陷数量最高的日期：{top_defect_date[DATE_COLUMN]}，"
                f"缺陷数量：{top_defect_date[DEFECT_COUNT_COLUMN]}"
            )

        available_dates = list(date_summary[DATE_COLUMN])
        selected_date = st.date_input(
            "选择日期查看当天异常记录",
            value=top_defect_date[DATE_COLUMN],
            min_value=min(available_dates),
            max_value=max(available_dates),
        )

        selected_records = filter_records_by_date(df, selected_date)
        trace_columns = [
            "日期",
            "批次号",
            "零件编号",
            "零件名称",
            "工序",
            "缺陷类型",
            "缺陷数量",
            "批次数量",
            "供应商",
            "责任部门",
            "严重等级",
            "处理状态",
        ]
        display_columns = [
            column for column in trace_columns if column in selected_records.columns
        ]

        if selected_records.empty:
            st.info("所选日期没有对应异常记录。")
        elif display_columns:
            records_to_show = selected_records[display_columns].copy()
            records_to_show[DATE_COLUMN] = pd.to_datetime(
                records_to_show[DATE_COLUMN],
                errors="coerce",
            ).dt.date
            st.dataframe(_style_df(records_to_show), width="stretch")
        else:
            st.dataframe(_style_df(selected_records), width="stretch")
    except ValueError as exc:
        st.warning(str(exc))
    except Exception as exc:
        st.error(f"日期趋势与批次追溯生成失败：{exc}")


def show_root_cause_analysis():
    st.markdown("### 缺陷根因自动关联")
    st.caption(
        "内置车削、铣削、磨削、钻削、铸造、焊接、装配七大工艺的缺陷根因知识库。"
        "选择工序类型和缺陷类型，自动匹配最可能的根因。"
    )

    process_types = get_all_process_types()

    selected_process = st.selectbox(
        "选择工序类型", ["（请选择）"] + process_types, key="rc_process"
    )

    if selected_process != "（请选择）":
        defect_options = get_defect_types_for_process(selected_process)
        selected_defect = st.selectbox(
            "选择缺陷类型",
            ["（请选择）"] + defect_options,
            key="rc_defect",
        )
    else:
        selected_defect = None

    if (
        selected_process
        and selected_process != "（请选择）"
        and selected_defect
        and selected_defect != "（请选择）"
    ):
        causes = get_root_causes(selected_process, selected_defect)

        if causes:
            st.markdown(
                f"**{selected_process} → {selected_defect}** 的可能根因："
            )

            enriched = []
            for c in causes:
                level_label, grade, color = probability_to_level(c["概率"])
                enriched.append({
                    "根因": c["根因"],
                    "发生等级": level_label,
                    "严重等级": grade,
                    "颜色": color,
                })

            chart_data = pd.DataFrame(enriched)
            bar_chart = px.bar(
                chart_data,
                x="严重等级",
                y="根因",
                orientation="h",
                title=f"{selected_defect} 根因分析（等级5=最高发，等级1=少见）",
                color="严重等级",
                color_continuous_scale="Reds",
                hover_data={"根因": True, "发生等级": True, "严重等级": True},
            )
            bar_chart.update_layout(
                yaxis=dict(autorange="reversed"),
                showlegend=False,
                xaxis=dict(tickmode="linear", tick0=1, dtick=1, range=[0.5, 5.5]),
            )
            st.plotly_chart(bar_chart, width="stretch", config={"displayModeBar": False})

            with st.expander("查看详细列表"):
                for item in enriched:
                    st.write(
                        f"- {item['根因']} —— 严重等级 {item['严重等级']}"
                        f"（{item['发生等级']}）"
                    )

            st.info(
                "根因排序基于机械加工常见经验统计，仅供参考。"
                "实际根因需结合现场设备、工艺参数和检测数据人工复核确认。"
            )
        else:
            st.warning(
                f"知识库中暂未收录「{selected_defect}」在"
                f"「{selected_process}」下的根因信息。"
            )


def _prepare_root_cause_pareto_df(defect_root_map, defect_summary):
    """Each defect attributed to ONE primary root cause (highest probability).

    This guarantees sum(root cause counts) = total defects.
    Then merge <= 5 into 其他 and sort by count descending.
    """
    aggregated = {}
    for defect, (_proc, causes) in defect_root_map.items():
        defect_count = int(
            defect_summary.loc[
                defect_summary["缺陷类型"] == defect, "缺陷数量"
            ].sum()
        )
        if not causes:
            continue
        # Pick the root cause with highest probability as the primary one
        primary = max(causes, key=lambda c: c["概率"])
        rc_name = primary["根因"]
        if rc_name not in aggregated:
            aggregated[rc_name] = {"根因": rc_name, "缺陷数量": 0}
        aggregated[rc_name]["缺陷数量"] += defect_count

    rc_list = sorted(aggregated.values(), key=lambda x: x["缺陷数量"], reverse=True)
    rc_df = pd.DataFrame(rc_list)

    # Merge <= 5 into 其他
    major = rc_df[rc_df["缺陷数量"] > 5].copy()
    minor = rc_df[rc_df["缺陷数量"] <= 5]
    if not minor.empty:
        other_count = int(minor["缺陷数量"].sum())
        other_row = pd.DataFrame([{"根因": "其他", "缺陷数量": other_count}])
        rc_df = pd.concat([major, other_row], ignore_index=True)
        rc_df = rc_df.sort_values("缺陷数量", ascending=False).reset_index(drop=True)

    total = rc_df["缺陷数量"].sum()
    rc_df["累计占比"] = rc_df["缺陷数量"].cumsum() / total if total > 0 else 0
    return rc_df


def show_bidirectional_pareto(df):
    st.subheader("缺陷-根因双向帕雷托分析")
    st.caption(
        "上图：缺陷类型帕雷托分布。下图：根因帕雷托分布（跨工序汇总）。"
        "选择缺陷查看对应根因，选择根因反向定位相关缺陷。"
    )

    defect_summary = summarize_by_defect_type(df)
    defect_list = defect_summary["缺陷类型"].tolist()

    defect_root_map = {}
    all_root_causes = set()
    root_cause_to_defects = {}

    for defect in defect_list:
        process_hint = None
        if "工序" in df.columns:
            proc_rows = df[df["缺陷类型"] == defect]["工序"]
            if not proc_rows.empty:
                process_hint = proc_rows.mode().iloc[0]

        matched_proc, causes = find_defect_root_causes(defect, process_hint)
        if causes:
            defect_root_map[defect] = (matched_proc, causes)
            for c in causes:
                rc_name = c["根因"]
                all_root_causes.add(rc_name)
                if rc_name not in root_cause_to_defects:
                    root_cause_to_defects[rc_name] = []
                root_cause_to_defects[rc_name].append(defect)

    if "bidir_defect" not in st.session_state:
        st.session_state["bidir_defect"] = None
    if "bidir_root_cause" not in st.session_state:
        st.session_state["bidir_root_cause"] = None

    # ===== TOP: Defect Pareto Chart (full width) =====
    pareto_df = prepare_pareto_data(df)
    if pareto_df.empty:
        st.warning("暂无可用于生成帕雷托图的数据。")
    else:
        highlight_indices = set()
        for i, d in enumerate(pareto_df["缺陷类型"]):
            if (
                st.session_state["bidir_root_cause"]
                and d in root_cause_to_defects.get(
                    st.session_state["bidir_root_cause"], []
                )
            ) or (
                st.session_state["bidir_defect"]
                and d == st.session_state["bidir_defect"]
            ):
                highlight_indices.add(i)

        fig_defect = create_pareto_chart(
            pareto_df, highlight_indices=highlight_indices
        )
        st.plotly_chart(
            fig_defect,
            width="stretch",
            key="bidir_defect_chart",
            config={"displayModeBar": False},
        )

    selected_defect = st.selectbox(
        "选择缺陷查看根因",
        ["（全部）"] + defect_list,
        key="bidir_defect_select",
    )
    if selected_defect != "（全部）":
        st.session_state["bidir_defect"] = selected_defect
        st.session_state["bidir_root_cause"] = None
    else:
        st.session_state["bidir_defect"] = None

    # ===== BOTTOM: Root Cause Pareto Chart (full width) =====
    rc_pareto_df = _prepare_root_cause_pareto_df(defect_root_map, defect_summary)

    if rc_pareto_df.empty:
        st.info("当前数据中的缺陷类型在知识库中暂无匹配的根因信息。")
    else:
        if st.session_state["bidir_defect"] and st.session_state["bidir_defect"] in defect_root_map:
            matched_proc, causes = defect_root_map[st.session_state["bidir_defect"]]
            st.caption(
                f"「{st.session_state['bidir_defect']}」"
                f"在 {matched_proc} 工艺中的根因（按概率估计贡献）："
            )
            # Estimate contribution per root cause using probability weighting
            total_prob = sum(c["概率"] for c in causes)
            single_list = []
            for c in causes:
                est_count = round(
                    defect_summary.loc[
                        defect_summary["缺陷类型"] == st.session_state["bidir_defect"],
                        "缺陷数量",
                    ].sum()
                    * c["概率"]
                    / total_prob
                ) if total_prob > 0 else 0
                single_list.append({"根因": c["根因"], "缺陷数量": est_count})
            single_list.sort(key=lambda x: x["缺陷数量"], reverse=True)
            single_df = pd.DataFrame(single_list)
            single_total = single_df["缺陷数量"].sum()
            single_df["累计占比"] = (
                single_df["缺陷数量"].cumsum() / single_total if single_total > 0 else 0
            )

            fig_rc = create_root_cause_pareto_chart(single_df)
            st.plotly_chart(
                fig_rc,
                width="stretch",
                key="bidir_rc_chart",
                config={"displayModeBar": False},
            )
        elif st.session_state["bidir_root_cause"]:
            related_defects = root_cause_to_defects.get(
                st.session_state["bidir_root_cause"], []
            )
            st.caption(
                f"根因「{st.session_state['bidir_root_cause']}」"
                f"相关的缺陷：{'、'.join(related_defects)}"
            )
            st.info("选择「（全部）」查看跨工序汇总根因帕累托图。")
        else:
            st.caption("跨工序汇总，将各缺陷数量叠加到对应根因。")
            fig_rc = create_root_cause_pareto_chart(rc_pareto_df)
            st.plotly_chart(
                fig_rc,
                width="stretch",
                key="bidir_rc_chart",
                config={"displayModeBar": False},
            )

    all_rc_list = sorted(all_root_causes)
    if all_rc_list:
        selected_rc = st.selectbox(
            "选择根因反向定位缺陷",
            ["（不选）"] + all_rc_list,
            key="bidir_rc_select",
        )
        if selected_rc != "（不选）":
            st.session_state["bidir_root_cause"] = selected_rc
            st.session_state["bidir_defect"] = None
        else:
            st.session_state["bidir_root_cause"] = None

    if not defect_root_map:
        st.info(
            "当前数据中的缺陷类型在知识库中暂无精确匹配，"
            "可在「根因分析」标签页手动查看。"
        )


def show_deepseek_quality_analysis(df, dataset_signature):
    """Generate and display a cached DeepSeek quality analysis on demand."""
    st.markdown("### DeepSeek AI 结构化分析")
    st.caption(
        "AI 仅分析聚合统计数据，不接收原始批次明细，也不判断具体缺陷根因。"
    )

    if st.session_state.get("deepseek_dataset_signature") != dataset_signature:
        st.session_state["deepseek_dataset_signature"] = dataset_signature
        st.session_state.pop("deepseek_quality_analysis", None)
        st.session_state.pop("deepseek_api_usage", None)
        st.session_state.pop("deepseek_quality_error", None)

    if st.button("生成 AI 质量分析", type="primary", key="generate_deepseek_analysis"):
        with st.spinner("正在调用 DeepSeek 分析统计结果……"):
            try:
                result = generate_deepseek_quality_analysis(df)
            except DeepSeekAnalysisError as exc:
                st.session_state.pop("deepseek_quality_analysis", None)
                st.session_state.pop("deepseek_api_usage", None)
                st.session_state["deepseek_quality_error"] = str(exc)
            else:
                st.session_state["deepseek_quality_analysis"] = (
                    result.analysis.model_dump()
                )
                st.session_state["deepseek_api_usage"] = result.usage.model_dump()
                st.session_state.pop("deepseek_quality_error", None)

    error_message = st.session_state.get("deepseek_quality_error")
    if error_message:
        st.warning(f"{error_message} 原有统计、传统摘要和报告导出仍可正常使用。")

    result = st.session_state.get("deepseek_quality_analysis")
    if not result:
        return

    st.markdown(f"**分析摘要：** {result['summary']}")
    st.markdown(f"**数据关注等级：{result['risk_level']}**")
    st.caption(
        "该等级仅表示当前统计数据的关注程度，不代表质量放行、正式工程风险或失效判定。"
    )

    st.markdown("**关键发现**")
    for item in result["key_findings"]:
        st.markdown(f"- {item}")

    st.markdown("**建议复核项**")
    for index, item in enumerate(result["recommended_checks"], start=1):
        st.markdown(f"{index}. {item}")

    usage = st.session_state.get("deepseek_api_usage", {})
    with st.expander("API 用量", expanded=False):
        st.caption("仅用于开发验收；不显示 API Key 或完整 Prompt。")

        def format_tokens(field_name):
            value = usage.get(field_name)
            return str(value) if value is not None else "未返回"

        st.write(f"输入 Tokens：{format_tokens('prompt_tokens')}")
        st.write(f"输出 Tokens：{format_tokens('completion_tokens')}")
        st.write(f"推理 Tokens：{format_tokens('reasoning_tokens')}")
        st.write(f"总 Tokens：{format_tokens('total_tokens')}")


# =============================================================================
# A-07 制造运营中心（工厂驾驶舱）
# =============================================================================


def build_inventory_status(inventory_df):
    """为库存数据补充「库存状态」与「缺口」两列。

    库存口径：stock < safety_stock 记为「预警」，
    缺口 = safety_stock - stock（仅保留不足部分，充足时为 0）。
    """
    if inventory_df.empty:
        return inventory_df.copy()

    df = inventory_df.copy()
    stock = pd.to_numeric(df["stock"], errors="coerce").fillna(0)
    safety_stock = pd.to_numeric(df["safety_stock"], errors="coerce").fillna(0)

    df["缺口"] = (safety_stock - stock).clip(lower=0).astype("int64")
    df["库存状态"] = "正常"
    df.loc[stock < safety_stock, "库存状态"] = "预警"
    return df


def to_inventory_display_frame(inventory_df):
    """库存展示表：中文表头 + 库存状态 + 缺口。"""
    display = inventory_df.rename(
        columns={
            "material": "物料",
            "stock": "当前库存",
            "safety_stock": "安全库存",
            "unit": "单位",
            "库存状态": "状态",
        }
    )
    columns = ["物料", "当前库存", "安全库存", "单位", "状态", "缺口"]
    return display[[column for column in columns if column in display.columns]]


def show_manufacturing_overview():
    """制造运营中心（工厂驾驶舱）：订单 / 库存 / 设备 / 质量 四个模块。"""
    st.subheader("🏭 制造运营中心")
    st.caption(
        "工厂驾驶舱总览。数据来自 data/ 目录下的 ERP 订单、原材料库存、设备台账、"
        "MES 生产、设备传感器与质量数据，均为模拟数据。"
    )

    orders_df = query_orders()
    inventory_df = build_inventory_status(query_inventory())
    equipment_df = query_equipment_status()
    production_df = query_production_capacity()

    order_summary = order_analysis.summarize_orders(orders_df)
    equipment_summary = equipment_analysis.summarize_equipment(equipment_df)
    production_summary = production_analysis.summarize_production(production_df)
    quality_overview = analyze_quality_overview()
    capacity = production_analysis.calculate_capacity_vs_demand(
        orders_df=orders_df,
        production_df=production_df,
    )

    material_count = int(len(inventory_df))
    shortage_df = inventory_df.loc[inventory_df["库存状态"] == "预警"]
    shortage_count = int(len(shortage_df))

    # ---------- 顶部关键指标 ----------
    metric_orders, metric_inventory, metric_equipment, metric_quality = st.columns(4)

    with metric_orders:
        st.metric(
            "在手订单",
            f"{order_summary['order_count']} 单",
            f"合计 {order_summary['total_quantity']} 件",
            delta_color="off",
        )
    with metric_inventory:
        st.metric(
            "原材料状态",
            f"{material_count - shortage_count} 项正常",
            f"{shortage_count} 项低于安全库存" if shortage_count else "无库存预警",
            delta_color="off",
        )
    with metric_equipment:
        st.metric(
            "设备正常 / 异常",
            f"{equipment_summary['normal_count']} / {equipment_summary['abnormal_count']}",
            f"设备正常率 {equipment_summary['normal_ratio']:.1%}",
            delta_color="off",
        )
    with metric_quality:
        st.metric(
            "质量缺陷总数",
            f"{quality_overview['total_defect_count']}",
            f"涉及 {quality_overview['defect_type_count']} 类缺陷",
            delta_color="off",
        )

    # ---------- 风险提示 ----------
    alerts = []
    if shortage_count:
        alerts.append(f"{shortage_count} 项原材料低于安全库存")
    if equipment_summary["abnormal_count"]:
        alerts.append(
            f"{equipment_summary['abnormal_count']} 台设备处于异常状态"
            f"（其中故障 {equipment_summary['fault_count']} 台）"
        )
    if capacity["capacity_risk"]:
        alerts.append("在手订单所需生产天数已超过最早交期可用天数")
    if alerts:
        st.warning("风险提示：" + "；".join(alerts) + "。")

    order_column, inventory_column = st.columns(2)

    # ---------- 模块 1：订单 ----------
    with order_column:
        with st.container(border=True):
            st.markdown("#### 📋 订单")
            st.caption("ERP 模拟订单数据（data/orders.csv）")
            st.write(
                f"当前订单数量：**{order_summary['order_count']} 单**，"
                f"合计 **{order_summary['total_quantity']} 件**，"
                f"高优先级 **{order_summary['high_priority_count']} 单**，"
                f"覆盖 **{order_summary['customer_count']} 家客户**。"
            )

            st.markdown("**订单优先级分布**")
            st.dataframe(
                _style_df(order_analysis.get_priority_breakdown(orders_df), ["占比"]),
                width="stretch",
                hide_index=True,
            )

            st.markdown("**最近交付订单**")
            st.dataframe(
                order_analysis.to_display_frame(
                    order_analysis.get_urgent_orders(orders_df, limit=5)
                ),
                width="stretch",
                hide_index=True,
            )

            if capacity["required_days"] is not None:
                st.caption(
                    f"产能测算：按在产日产能 {capacity['daily_capacity']} 件，"
                    f"完成在手订单约需 {capacity['required_days']} 天；"
                    f"最早交期 {capacity['earliest_deadline']}"
                    f"（距今 {capacity['available_days']} 天）。"
                )

            for line in order_analysis.order_insights(orders_df):
                st.caption(f"· {line}")

    # ---------- 模块 2：库存 ----------
    with inventory_column:
        with st.container(border=True):
            st.markdown("#### 📦 库存")
            st.caption("原材料库存数据（data/inventory.csv）")
            st.write(
                f"原材料 **{material_count} 项**，"
                f"其中低于安全库存 **{shortage_count} 项**。"
            )

            if shortage_df.empty:
                st.success("所有原材料库存均在安全库存之上。")
            else:
                st.markdown("**库存预警物料**")
                st.dataframe(
                    to_inventory_display_frame(
                        shortage_df.sort_values("缺口", ascending=False)
                    ),
                    width="stretch",
                    hide_index=True,
                )

            with st.expander("查看全部原材料库存"):
                st.dataframe(
                    to_inventory_display_frame(inventory_df),
                    width="stretch",
                    hide_index=True,
                )

    equipment_column, quality_column = st.columns(2)

    # ---------- 模块 3：设备 ----------
    with equipment_column:
        with st.container(border=True):
            st.markdown("#### ⚙️ 设备")
            st.caption("设备台账数据（data/equipment.csv）")
            st.write(
                f"正常设备 **{equipment_summary['normal_count']} 台**，"
                f"异常设备 **{equipment_summary['abnormal_count']} 台**"
                f"（预警 {equipment_summary['warning_count']}、"
                f"故障 {equipment_summary['fault_count']}）。"
            )

            st.dataframe(
                _style_df(equipment_analysis.get_status_breakdown(equipment_df), ["占比"]),
                width="stretch",
                hide_index=True,
            )

            abnormal_df = equipment_analysis.get_abnormal_equipment(equipment_df)
            if abnormal_df.empty:
                st.success("当前没有异常设备。")
            else:
                st.markdown("**异常设备清单**")
                st.dataframe(
                    equipment_analysis.to_display_frame(abnormal_df),
                    width="stretch",
                    hide_index=True,
                )

            maintenance_due = equipment_analysis.get_maintenance_due(equipment_df)
            if not maintenance_due.empty:
                st.warning(
                    "维保超期设备："
                    + "、".join(maintenance_due["equipment_id"].tolist())
                )

            sensor_df = read_data_csv("iot_sensor.csv")
            with st.expander(f"设备传感器数据（共 {len(sensor_df)} 条）"):
                st.caption(f"最新采集时间：{sensor_df['timestamp'].max()}")
                st.dataframe(
                    sensor_df.tail(6),
                    width="stretch",
                    hide_index=True,
                )

    # ---------- 模块 4：质量（沿用原有质量分析） ----------
    with quality_column:
        with st.container(border=True):
            st.markdown("#### ✅ 质量")
            st.caption(
                "沿用原有质量分析逻辑：modules/quality_analysis.py + data/quality.csv"
            )

            quality_metric_count, quality_metric_type = st.columns(2)
            with quality_metric_count:
                st.metric("总缺陷数量", quality_overview["total_defect_count"])
            with quality_metric_type:
                st.metric("缺陷类型数量", quality_overview["defect_type_count"])

            if quality_overview["missing_columns"]:
                st.warning(
                    "质量数据缺少必要字段："
                    + "、".join(quality_overview["missing_columns"])
                )
            else:
                st.write(
                    f"主要缺陷类型：**{quality_overview['top_defect_type']}**"
                    f"（{quality_overview['top_defect_count']} 件）；"
                    f"质量记录 {quality_overview['record_count']} 条。"
                )

                st.dataframe(
                    _style_df(
                        quality_overview["defect_summary"].head(6),
                        ["占比"],
                    ),
                    width="stretch",
                    hide_index=True,
                )

                with st.expander("质量分析摘要（原规则摘要）"):
                    for line in quality_overview["summary_lines"]:
                        st.markdown(f"- {line}")

            st.caption("帕雷托分析、根因分析、AI 分析与报告导出见「🔍 质量分析」标签页。")

    # ---------- 生产能力明细（MES） ----------
    with st.expander("生产能力明细（MES 生产数据 data/production.csv）"):
        st.write(
            f"MES 覆盖 **{production_summary['product_count']} 种产品**、"
            f"**{production_summary['process_count']} 道工序**、"
            f"**{production_summary['equipment_count']} 台设备**，"
            f"共 {production_summary['line_count']} 条产线；"
            f"总日产能 **{production_summary['total_daily_capacity']} 件**，"
            f"在产日产能 **{production_summary['running_daily_capacity']} 件**，"
            f"在产平均良率 **{production_summary['average_yield_rate']:.1%}**。"
        )

        st.markdown("**按工序汇总**")
        st.dataframe(
            _style_df(
                production_analysis.get_process_breakdown(production_df),
                ["平均良率"],
            ),
            width="stretch",
            hide_index=True,
        )

        st.markdown("**产线明细**")
        st.dataframe(
            production_analysis.to_display_frame(production_df),
            width="stretch",
            hide_index=True,
        )

        for line in production_analysis.production_insights(
            orders_df=orders_df,
            production_df=production_df,
        ):
            st.caption(f"· {line}")


def show_quality_analysis_page():
    """原有质量分析页面：原 app.py 主体逻辑，保持不变，仅在 Tab 内渲染。"""
    st.caption("打开页面即可使用内置示例数据完整演示；也可以切换为上传自己的文件。")

    data_source = st.radio(
        "数据来源",
        ["内置示例数据", "上传自己的文件"],
        horizontal=True,
    )

    if data_source == "内置示例数据":
        sample_dir = Path(__file__).resolve().parent / "sample_data"
        try:
            sample_files = list_sample_files(sample_dir)
            selected_sample_name = st.selectbox(
                "选择演示数据",
                [path.name for path in sample_files],
                help="默认样例覆盖零件、工序、供应商、严重等级、日期趋势和报告导出。",
            )
            selected_sample_path = next(
                path for path in sample_files if path.name == selected_sample_name
            )
            uploaded_file = load_sample_upload(selected_sample_path)
            st.info(f"当前使用演示数据：{selected_sample_name}")
        except (FileNotFoundError, OSError) as exc:
            uploaded_file = None
            st.error(f"示例数据加载失败：{exc}")
    else:
        uploaded_file = st.file_uploader(
            "上传质量异常记录文件",
            type=["csv", "xlsx", "xls"],
        )

    if uploaded_file is None:
        if data_source == "上传自己的文件":
            st.info("请上传 csv、xlsx 或 xls 文件。")
    else:
        try:
            df = load_quality_file(uploaded_file)
        except Exception as exc:
            st.error(f"文件读取失败：{exc}")
        else:
            st.success("文件读取成功。")

            row_count, column_count = df.shape
            st.write(f"数据行数：{row_count}")
            st.write(f"数据列数：{column_count}")

            missing_columns = validate_required_columns(df)
            if missing_columns:
                st.warning("缺少必要字段：" + "、".join(missing_columns))
            else:
                st.success("必要字段检查通过。")

                defect_summary = summarize_by_defect_type(df)
                total_defect_count = defect_summary["缺陷数量"].sum()
                defect_type_count = len(defect_summary)

                st.subheader("缺陷类型统计")
                st.write(f"总缺陷数量：{total_defect_count}")
                st.write(f"缺陷类型数量：{defect_type_count}")
                st.dataframe(_style_df(defect_summary, ["占比"]), width="stretch")

                try:
                    show_bidirectional_pareto(df)
                except ValueError as exc:
                    st.warning(str(exc))
                except Exception as exc:
                    st.error(f"帕雷托图生成失败：{exc}")

                st.subheader("多维度问题定位")
                part_tab, process_tab, supplier_tab, severity_tab, root_cause_tab = st.tabs(
                    ["零件", "工序", "供应商", "严重等级", "根因分析"]
                )
                with part_tab:
                    show_dimension_analysis(df, "零件名称", "零件")
                with process_tab:
                    show_dimension_analysis(df, "工序", "工序")
                with supplier_tab:
                    show_dimension_analysis(df, "供应商", "供应商")
                with severity_tab:
                    show_dimension_analysis(df, "严重等级", "严重等级")
                with root_cause_tab:
                    show_root_cause_analysis()

                st.subheader("质量分析摘要")
                try:
                    quality_summary = generate_quality_summary(df)
                    for item in quality_summary:
                        st.markdown(f"- {item}")
                except Exception as exc:
                    st.error(f"质量分析摘要生成失败：{exc}")

                dataset_signature = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
                show_deepseek_quality_analysis(df, dataset_signature)

            show_date_trend_and_trace(df)

            st.subheader("QC 统计图表")
            qc_col1, qc_col2 = st.columns(2)

            with qc_col1:
                st.markdown("#### 缺陷数量直方图")
                try:
                    hist_fig = create_histogram(df)
                    st.plotly_chart(hist_fig, width="stretch", key="qc_histogram", config={"displayModeBar": False})
                except Exception as exc:
                    st.warning(f"直方图生成失败：{exc}")

            with qc_col2:
                st.markdown("#### 每日缺陷控制图")
                try:
                    date_summary_for_ctrl = summarize_by_date(df)
                    if date_summary_for_ctrl.empty:
                        st.info("暂无可用于生成控制图的数据。")
                    else:
                        ctrl_fig = create_control_chart(date_summary_for_ctrl)
                        st.plotly_chart(ctrl_fig, width="stretch", key="qc_control", config={"displayModeBar": False})
                except Exception as exc:
                    st.warning(f"控制图生成失败：{exc}")

            st.subheader("导出分析报告")
            col1, col2 = st.columns(2)
            with col1:
                try:
                    report_bytes = build_excel_report(df)
                    st.download_button(
                        label="下载 Excel 分析报告",
                        data=report_bytes,
                        file_name="quality_analysis_report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                except Exception as exc:
                    st.error(f"Excel 报告生成失败：{exc}")
            with col2:
                try:
                    word_bytes = build_word_report(df)
                    st.download_button(
                        label="下载 Word 8D 分析报告",
                        data=word_bytes,
                        file_name="8D_quality_report.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                except Exception as exc:
                    st.error(f"Word 8D 报告生成失败：{exc}")


# =============================================================================
# 页面入口：制造运营中心（新增 Tab）+ 质量分析（原有页面，保持不变）
# =============================================================================

st.set_page_config(
    page_title="Manufacturing Quality Tool",
    layout="wide",
)

st.title("制造质量数据分析与检验计划辅助工具")

overview_tab, quality_tab = st.tabs(["🏭 制造运营中心", "🔍 质量分析"])

with overview_tab:
    show_manufacturing_overview()

with quality_tab:
    show_quality_analysis_page()
