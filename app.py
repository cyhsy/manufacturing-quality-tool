import pandas as pd
import plotly.express as px
import streamlit as st

from src.charts import (
    create_control_chart,
    create_date_trend_chart,
    create_histogram,
    create_pareto_chart,
    create_root_cause_pareto_chart,
)
from src.defect_analysis import (
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
from src.data_loader import load_quality_file, validate_required_columns
from src.report_generator import build_excel_report
from src.root_cause_engine import (
    find_defect_root_causes,
    get_all_process_types,
    get_defect_types_for_process,
    get_root_causes,
    probability_to_level,
)
from src.word_report_generator import build_word_report


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
            ):
                highlight_indices.add(i)
            elif (
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


st.set_page_config(
    page_title="Manufacturing Quality Tool",
    layout="wide",
)

st.title("制造质量数据分析与检验计划辅助工具")

uploaded_file = st.file_uploader(
    "上传质量异常记录文件",
    type=["csv", "xlsx", "xls"],
)

if uploaded_file is None:
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
