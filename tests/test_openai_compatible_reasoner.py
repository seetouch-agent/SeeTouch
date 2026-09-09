"""OpenAICompatibleReasoner 单元测试。"""

from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion
from PIL import Image

from seetouch.cli.main import _build_parser
from seetouch.reasoning.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleReasoner,
)


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1/")
    monkeypatch.setenv("OPENAI_MODEL_ID", "vision-model")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")

    config = OpenAICompatibleConfig.from_env()

    assert config.api_key == "test-key"
    assert config.base_url == "https://example.com/v1"
    assert config.model_id == "vision-model"
    assert config.reasoning_effort == "high"


def test_config_defaults_and_vlm_key_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL_ID", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("SEETOUCH_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("VLM_API_KEY", "fallback-key")

    config = OpenAICompatibleConfig.from_env()

    assert config.api_key == "fallback-key"
    assert config.base_url == "https://api.openai.com/v1"
    assert config.model_id == "gpt-4.1-mini"
    assert config.reasoning_effort is None


def test_config_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VLM_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="missing OPENAI_API_KEY"):
        OpenAICompatibleConfig.from_env()


def test_config_rejects_unknown_reasoning_effort():
    with pytest.raises(ValueError, match="reasoning_effort"):
        OpenAICompatibleConfig(api_key="test-key", reasoning_effort="extreme")


def test_config_normalizes_reasoning_effort():
    config = OpenAICompatibleConfig(api_key="test-key", reasoning_effort=" HIGH ")
    default_config = OpenAICompatibleConfig(
        api_key="test-key",
        reasoning_effort="default",
    )

    assert config.reasoning_effort == "high"
    assert default_config.reasoning_effort is None


def test_api_request_includes_reasoning_effort(monkeypatch):
    calls = []
    response = _chat_completion()

    class FakeOpenAI:
        def __init__(self, *, base_url, api_key):
            assert base_url == "https://example.com/v1"
            assert api_key == "test-key"
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: calls.append(kwargs) or response
                )
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    reasoner = OpenAICompatibleReasoner(
        OpenAICompatibleConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model_id="vision-model",
            reasoning_effort="medium",
            max_tokens=1024,
        )
    )

    output = reasoner.predict(
        "完成任务",
        Image.new("RGB", (20, 40), "black"),
        [],
    )

    assert output.action.type == "COMPLETE"
    assert output.reasoning_content == "分析屏幕后确认完成"
    assert output.usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "reasoning_tokens": 3,
    }
    assert calls[0]["model"] == "vision-model"
    assert calls[0]["max_tokens"] == 1024
    assert calls[0]["extra_body"] == {"reasoning_effort": "medium"}
    image_url = calls[0]["messages"][1]["content"][0]["image_url"]["url"]
    assert image_url.startswith("data:image/")


def test_reasoning_effort_omitted_when_using_model_default(monkeypatch):
    calls = []

    class FakeOpenAI:
        def __init__(self, *, base_url, api_key):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: calls.append(kwargs) or _chat_completion()
                )
            )

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    reasoner = OpenAICompatibleReasoner(OpenAICompatibleConfig(api_key="test-key"))
    reasoner.predict("完成任务", Image.new("RGB", (20, 40), "black"), [])

    assert "extra_body" not in calls[0]


def test_cli_defaults_to_openai_compatible_reasoner():
    args = _build_parser().parse_args(["run", "打开设置"])
    debug_args = _build_parser().parse_args(["debug"])

    assert args.reasoner == "openai"
    assert debug_args.reasoner == "openai"


def _chat_completion() -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "completion-1",
            "object": "chat.completion",
            "created": 0,
            "model": "vision-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"screen_summary":"任务完成","action_summary":"结束",'
                            '"action":"COMPLETE","parameters":{}}'
                        ),
                        "reasoning_content": "分析屏幕后确认完成",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        }
    )
