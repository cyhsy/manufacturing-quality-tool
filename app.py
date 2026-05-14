import streamlit as st

from src.charts import create_pareto_chart
from src.defect_analysis import prepare_pareto_data, summarize_by_defect_type
from src.data_loader import load_quality_file, validate_required_columns


st.set_page_config(
    page_title="Manufacturing Quality Tool",
    layout="wide",
)

st.title("制造质量数据分析与检验计划辅助工具")
st.write(
    "当前阶段：A 模块 MVP，支持质量异常记录 Excel/CSV 上传与预览。"
)

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
            st.dataframe(defect_summary, width="stretch")

            st.subheader("缺陷类型 Pareto 图")
            try:
                pareto_df = prepare_pareto_data(df)
                if pareto_df.empty:
                    st.warning("暂无可用于生成 Pareto 图的数据。")
                else:
                    pareto_chart = create_pareto_chart(pareto_df)
                    st.plotly_chart(pareto_chart, width="stretch")
            except ValueError as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"Pareto 图生成失败：{exc}")

        st.subheader("当前文件字段列表")
        st.write(list(df.columns))

        st.subheader("原始数据前 20 行预览")
        st.dataframe(df.head(20), width="stretch")
