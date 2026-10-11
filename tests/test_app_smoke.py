"""Streamlit 端到端冒烟测试（AppTest）。

验证 A-07 交付目标：
1. 打开网页即可看到「制造运营中心」工厂驾驶舱，且订单/库存/设备/质量四个模块渲染正常；
2. 原有「质量分析」页面功能未被破坏（示例数据加载、字段校验、帕雷托、根因、
   图表、Excel/Word 报告导出仍在）。
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from modules.quality_analysis import analyze_quality_overview


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


@pytest.fixture(scope="module")
def app():
    app_test = AppTest.from_file(str(APP_PATH), default_timeout=300)
    app_test.run()
    return app_test


def _labels(elements):
    return [str(element.label) for element in elements]


def _values(elements):
    return [str(element.value) for element in elements]


def test_app_runs_without_exception(app):
    assert not app.exception, [str(item) for item in app.exception]


def test_both_top_level_tabs_exist(app):
    labels = _labels(app.tabs)

    assert "🏭 制造运营中心" in labels
    assert "🔍 质量分析" in labels


def test_original_quality_sub_tabs_still_exist(app):
    labels = _labels(app.tabs)

    for label in ["零件", "工序", "供应商", "严重等级", "根因分析"]:
        assert label in labels, f"原有质量分析子标签丢失：{label}"


def test_cockpit_kpi_metrics_match_data(app):
    metrics = {element.label: element.value for element in app.metric}

    assert metrics["在手订单"] == "15 单"
    assert metrics["原材料状态"] == "9 项正常"
    assert metrics["设备正常 / 异常"] == "10 / 5"

    overview = analyze_quality_overview()
    expected_defects = str(overview["total_defect_count"])
    assert metrics["质量缺陷总数"] == expected_defects
    assert metrics["总缺陷数量"] == expected_defects
    assert metrics["缺陷类型数量"] == str(overview["defect_type_count"])


def test_cockpit_shows_four_modules(app):
    markdown_values = " ".join(_values(app.markdown))

    for module_title in ["#### 📋 订单", "#### 📦 库存", "#### ⚙️ 设备", "#### ✅ 质量"]:
        assert module_title in markdown_values, f"驾驶舱缺少模块：{module_title}"

    assert "🏭 制造运营中心" in _values(app.subheader)


def test_cockpit_raises_risk_and_maintenance_alerts(app):
    warnings = " ".join(_values(app.warning))

    assert "风险提示" in warnings
    assert "4 项原材料低于安全库存" in warnings
    assert "5 台设备处于异常状态" in warnings
    assert "维保超期设备" in warnings


def test_cockpit_renders_tables_and_capacity_section(app):
    assert len(app.dataframe) >= 8

    expander_labels = _labels(app.expander)
    assert any("生产能力明细" in label for label in expander_labels)
    assert any("设备传感器数据" in label for label in expander_labels)


def test_original_quality_page_still_loads_demo_data(app):
    successes = " ".join(_values(app.success))

    assert "文件读取成功" in successes
    assert "必要字段检查通过" in successes
    assert "缺陷类型统计" in _values(app.subheader)


def test_original_quality_charts_and_exports_still_render(app):
    assert len(app.get("plotly_chart")) >= 5, "原有帕雷托/直方图/控制图缺失"

    download_buttons = _labels(app.get("download_button"))
    assert "下载 Excel 分析报告" in download_buttons
    assert "下载 Word 8D 分析报告" in download_buttons

    assert "生成 AI 质量分析" in _labels(app.button)


def test_original_demo_sample_files_are_still_available(app):
    select_boxes = [element for element in app.selectbox if element.label == "选择演示数据"]
    assert select_boxes, "示例数据选择器缺失"

    options = list(select_boxes[0].options)
    assert "质量异常记录样本.xlsx" in options
    assert len(options) == 7
