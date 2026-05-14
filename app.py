import streamlit as st

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

        st.subheader("当前文件字段列表")
        st.write(list(df.columns))

        st.subheader("原始数据前 20 行预览")
        st.dataframe(df.head(20), width="stretch")
