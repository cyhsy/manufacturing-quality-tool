import json
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

import modules.llm_quality_analysis as llm_module
from modules.llm_quality_analysis import (
    DEEPSEEK_MAX_OUTPUT_TOKENS,
    DEFAULT_DEEPSEEK_BASE_URL,
    DeepSeekAnalysisError,
    DeepSeekAnalysisResult,
    QualityAnalysis,
    build_quality_statistics,
    create_deepseek_client,
    generate_deepseek_quality_analysis,
)


def build_llm_test_data():
    return pd.DataFrame(
        {
            "日期": ["2026-05-14", "2026-05-14", "2026-05-15"],
            "零件名称": ["支架", "支架", "外壳"],
            "工序": ["铣削", "铣削", "检验"],
            "缺陷类型": ["划伤", "划伤", "变形"],
            "缺陷数量": [4, 2, 1],
            "供应商": ["A供应商", "A供应商", "B供应商"],
            "严重等级": ["高", "高", "中"],
        }
    )


class FakeCompletions:
    def __init__(self, content, finish_reason="stop", usage=None):
        self.content = content
        self.finish_reason = finish_reason
        self.usage = usage
        self.call_kwargs = None

    def create(self, **kwargs):
        self.call_kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=self.finish_reason,
                    message=SimpleNamespace(content=self.content),
                )
            ],
            usage=self.usage,
        )


class FakeClient:
    def __init__(self, content, finish_reason="stop", usage=None):
        self.completions = FakeCompletions(content, finish_reason, usage)
        self.chat = SimpleNamespace(completions=self.completions)


def valid_analysis_json():
    return json.dumps(
        {
            "summary": "当前缺陷主要集中在划伤类型。",
            "key_findings": ["划伤共6件，占全部缺陷的85.71%。"],
            "risk_level": "中",
            "recommended_checks": ["复核划伤相关批次的检测记录。"],
        },
        ensure_ascii=False,
    )


def test_build_quality_statistics_uses_existing_aggregations_and_is_json_serializable():
    statistics = build_quality_statistics(build_llm_test_data())

    assert statistics["overview"] == {
        "record_count": 3,
        "total_defect_count": 7,
        "defect_type_count": 2,
    }
    assert statistics["defect_distribution"]["items"][0]["name"] == "划伤"
    assert statistics["severity"]["high_severity_defect_count"] == 6
    assert statistics["date_trend"]["peak_date"]["date"] == "2026-05-14"
    json.dumps(statistics, ensure_ascii=False, allow_nan=False)


def test_quality_analysis_rejects_invalid_risk_level():
    with pytest.raises(ValidationError):
        QualityAnalysis.model_validate(
            {
                "summary": "摘要",
                "key_findings": ["发现"],
                "risk_level": "严重",
                "recommended_checks": ["复核"],
            }
        )


def test_generate_deepseek_analysis_requests_json_output_and_validates_response():
    fake_client = FakeClient(valid_analysis_json())

    result = generate_deepseek_quality_analysis(
        build_llm_test_data(),
        client=fake_client,
        model="deepseek-v4-flash",
    )

    assert isinstance(result, DeepSeekAnalysisResult)
    assert isinstance(result.analysis, QualityAnalysis)
    assert result.analysis.risk_level == "中"
    call = fake_client.completions.call_kwargs
    assert call["model"] == "deepseek-v4-flash"
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert call["max_tokens"] == DEEPSEEK_MAX_OUTPUT_TOKENS == 800
    assert "JSON" in call["messages"][0]["content"]
    assert "具体缺陷根因" in call["messages"][0]["content"]


def test_generate_deepseek_analysis_returns_usage_including_reasoning_tokens():
    usage = SimpleNamespace(
        prompt_tokens=321,
        completion_tokens=96,
        total_tokens=417,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
    )
    fake_client = FakeClient(valid_analysis_json(), usage=usage)

    result = generate_deepseek_quality_analysis(
        build_llm_test_data(),
        client=fake_client,
    )

    assert result.usage.model_dump() == {
        "prompt_tokens": 321,
        "completion_tokens": 96,
        "reasoning_tokens": 0,
        "total_tokens": 417,
    }


def test_generate_deepseek_analysis_tolerates_missing_usage_fields():
    result = generate_deepseek_quality_analysis(
        build_llm_test_data(),
        client=FakeClient(valid_analysis_json()),
    )

    assert result.usage.model_dump() == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
    }


def test_generate_deepseek_analysis_uses_model_from_environment(monkeypatch):
    fake_client = FakeClient(valid_analysis_json())
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    generate_deepseek_quality_analysis(
        build_llm_test_data(),
        client=fake_client,
    )

    assert fake_client.completions.call_kwargs["model"] == "deepseek-v4-pro"


def test_generate_deepseek_analysis_wraps_api_errors():
    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("network unavailable")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailingCompletions())
    )

    with pytest.raises(DeepSeekAnalysisError, match="API 调用失败"):
        generate_deepseek_quality_analysis(
            build_llm_test_data(),
            client=fake_client,
        )


def test_generate_deepseek_analysis_wraps_statistics_errors():
    incomplete_df = build_llm_test_data().drop(columns=["日期"])

    with pytest.raises(DeepSeekAnalysisError, match="无法整理为 LLM 输入"):
        generate_deepseek_quality_analysis(
            incomplete_df,
            client=FakeClient(valid_analysis_json()),
        )


@pytest.mark.parametrize(
    ("content", "finish_reason", "message"),
    [
        ("not json", "stop", "不是合法 JSON"),
        ('{"summary": "字段不完整"}', "stop", "未通过结构校验"),
        (valid_analysis_json(), "length", "未正常完成"),
        ("", "stop", "返回内容为空"),
    ],
)
def test_generate_deepseek_analysis_rejects_unusable_responses(
    content, finish_reason, message
):
    fake_client = FakeClient(content, finish_reason)

    with pytest.raises(DeepSeekAnalysisError, match=message):
        generate_deepseek_quality_analysis(
            build_llm_test_data(),
            client=fake_client,
        )


def test_create_deepseek_client_requires_environment_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(DeepSeekAnalysisError, match="DEEPSEEK_API_KEY"):
        create_deepseek_client()


def test_create_deepseek_client_uses_deepseek_environment_variables(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.deepseek.test")
    monkeypatch.setattr(llm_module, "OpenAI", fake_openai)

    create_deepseek_client()

    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://example.deepseek.test"


def test_create_deepseek_client_uses_default_base_url(monkeypatch):
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.setattr(llm_module, "OpenAI", fake_openai)

    create_deepseek_client()

    assert captured["base_url"] == DEFAULT_DEEPSEEK_BASE_URL


def test_create_deepseek_client_wraps_initialization_errors(monkeypatch):
    def failing_openai(**kwargs):
        raise ValueError("invalid client config")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(llm_module, "OpenAI", failing_openai)

    with pytest.raises(DeepSeekAnalysisError, match="客户端初始化失败"):
        create_deepseek_client()
