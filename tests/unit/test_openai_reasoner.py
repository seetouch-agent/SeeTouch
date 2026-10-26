from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from openai import OpenAI
from PIL import Image

try:
    import httpx2 as httpx
except ImportError:
    import httpx

from seetouch.cli.main import _build_parser
from seetouch.core.exceptions import VLMAPIError
from seetouch.core.runner import Runner
from seetouch.core.task import Task
from seetouch.reasoning.openai import OpenAIConfig, OpenAIReasoner


def test_proxy_request_and_action():
    requests = []

    def handler(request):
        import json

        requests.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == "proxy-vision"
        assert payload["messages"][0]["role"] == "system"
        content = payload["messages"][1]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["image_url"]["url"].startswith("data:image/")
        assert "thinking" not in payload
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": "proxy-vision",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant",
                "content": '{"action":"CLICK","parameters":{"point":[500,300]}}',
            }}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        })

    config = OpenAIConfig("test-key", "proxy-vision", "https://proxy.example/custom/v1/")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with OpenAI(
            api_key=config.api_key, base_url=config.base_url, http_client=http_client,
        ) as client:
            with patch("openai.OpenAI", return_value=client):
                reasoner = OpenAIReasoner(config)
            output = reasoner.predict("打开设置", Image.new("RGB", (100, 200)), [])
    assert str(requests[0].url) == "https://proxy.example/custom/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert output.action.type == "CLICK"
    assert output.usage["total_tokens"] == 20


@pytest.mark.parametrize("content,finish_reason", [
    (None, "stop"), ("{}", "length"),
    ('{"action":"COMPLETE","parameters":{}}', "content_filter"),
    ('{"action":"COMPLETE","parameters":{}}', "tool_calls"),
])
def test_invalid_response_fails(content, finish_reason):
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason=finish_reason,
    )])
    with patch("openai.OpenAI", return_value=client):
        reasoner = OpenAIReasoner(OpenAIConfig("test-key", "vision-model"))
    with pytest.raises(VLMAPIError):
        reasoner.predict("test", Image.new("RGB", (10, 10)), [])


def test_api_failure_aborts_runner(tmp_path):
    client = Mock()
    client.chat.completions.create.side_effect = RuntimeError("upstream unavailable")
    with patch("openai.OpenAI", return_value=client):
        reasoner = OpenAIReasoner(OpenAIConfig("test-key", "vision-model"))
    device = Mock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    result = Runner(device, reasoner, runs_dir=tmp_path).run(Task("打开设置"))
    assert result.completed is False
    assert "reasoning_failed" in result.aborted_reason
    device.click.assert_not_called()
    assert (tmp_path / result.task_id / "summary.json").exists()
    assert (tmp_path / result.task_id / "trace.jsonl").exists()


def test_environment_and_cli(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL_ID", "vision-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example/v1")
    assert OpenAIConfig.from_env().base_url == "https://proxy.example/v1"
    args = _build_parser().parse_args(["run", "打开设置", "--reasoner", "openai"])
    assert args.reasoner == "openai"


@pytest.mark.parametrize("base_url", [
    "https://proxy.example/v1/chat/completions", "invalid", "https://user:key@proxy.example/v1",
])
def test_invalid_base_url(base_url):
    with pytest.raises(ValueError):
        OpenAIConfig("test-key", "vision-model", base_url)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIConfig.from_env()


def test_responses_image_request():
    import json

    def handler(request):
        assert str(request.url) == "https://proxy.example/v1/responses"
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert payload["input"][0]["role"] == "system"
        content = payload["input"][1]["content"]
        assert content[0]["type"] == "input_text"
        assert content[1]["type"] == "input_image"
        assert content[1]["image_url"].startswith("data:image/")
        assert "messages" not in payload
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0,
            "model": "vision", "status": "completed",
            "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                        "status": "completed", "content": [{"type": "output_text",
                        "text": '{"action":"COMPLETE","parameters":{}}',
                        "annotations": []}]}],
            "usage": {"input_tokens": 15, "output_tokens": 5, "total_tokens": 20},
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with OpenAI(api_key="test", base_url="https://proxy.example/v1",
                    http_client=http_client) as client:
            with patch("openai.OpenAI", return_value=client):
                reasoner = OpenAIReasoner(OpenAIConfig(
                    "test", "vision", "https://proxy.example/v1", api_mode="responses",
                ))
            output = reasoner.predict("test", Image.new("RGB", (64, 64)), [])
    assert output.action.type == "COMPLETE"
    assert output.usage == {"input_tokens": 15, "output_tokens": 5, "total_tokens": 20,
                           "cached_tokens": 0}


@pytest.mark.parametrize("status", ["incomplete", "failed"])
def test_responses_incomplete_fails(status):
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(status=status)
    with patch("openai.OpenAI", return_value=client):
        reasoner = OpenAIReasoner(OpenAIConfig("test", "vision", api_mode="responses"))
    with pytest.raises(VLMAPIError):
        reasoner.predict("test", Image.new("RGB", (64, 64)), [])
    client.chat.completions.create.assert_not_called()


def test_invalid_api_mode():
    with pytest.raises(ValueError, match="OPENAI_API_MODE"):
        OpenAIConfig("test", "vision", api_mode="unknown")


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="TIMEOUT"):
        OpenAIConfig("test", "vision", timeout=timeout)


def test_responses_rejects_old_sdk_before_starting_task():
    client = SimpleNamespace(chat=Mock(), close=Mock())
    with patch("openai.OpenAI", return_value=client):
        with pytest.raises(RuntimeError, match="openai>=1.66.0"):
            OpenAIReasoner(OpenAIConfig("test", "vision", api_mode="responses"))
    client.close.assert_called_once()
    client.chat.completions.create.assert_not_called()
