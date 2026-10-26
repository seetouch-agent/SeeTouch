"""Exercise the authenticated HTTP fallback used by Android's actual pinned SDK."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from openai import OpenAI
from PIL import Image

from seetouch.core.runner import Runner
from seetouch.core.task import Task
from seetouch.reasoning.openai import OpenAIConfig, OpenAIReasoner
from seetouch.reasoning.responses_transport import create_response


ACTION = '{"action":"CLICK","parameters":{"point":[500,300]}}'


def response_body(text=ACTION):
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {"input_tokens": 15, "output_tokens": 5, "total_tokens": 20},
    }


@pytest.mark.parametrize("effort", [None, "high", "none"])
def test_legacy_transport_preserves_authenticated_image_request(effort):
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://proxy.example/custom/v1/responses"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "vision"
        assert payload["store"] is False
        assert payload["input"][0]["role"] == "system"
        content = payload["input"][1]["content"]
        assert content[0]["type"] == "input_text"
        assert content[1]["type"] == "input_image"
        assert content[1]["image_url"].startswith("data:image/")
        assert "messages" not in payload
        assert "thinking" not in payload
        assert payload.get("reasoning") == ({"effort": effort} if effort else None)
        return httpx.Response(200, json=response_body())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with OpenAI(api_key="test-key", base_url="https://proxy.example/custom/v1",
                    timeout=120, max_retries=0, http_client=http_client) as client:
            # Force the same public post() path even when running tests with a newer SDK.
            legacy = SimpleNamespace(post=client.post, close=client.close)
            with patch("openai.OpenAI", return_value=legacy):
                reasoner = OpenAIReasoner(OpenAIConfig(
                    "test-key", "vision", api_mode="responses", reasoning_effort=effort,
                ))
            output = reasoner.predict("打开设置", Image.new("RGB", (64, 64)), [])
        assert len(requests) == 1
    assert requests[0].extensions["timeout"]["read"] == 120
    assert output.action.type == "CLICK"
    assert output.usage == {"input_tokens": 15, "output_tokens": 5, "total_tokens": 20,
                           "cached_tokens": 0}


@pytest.mark.parametrize("status", ["incomplete", "failed", "queued", "in_progress", None])
def test_legacy_incomplete_response_never_executes_action(tmp_path, status):
    body = response_body()
    body["status"] = status
    client = SimpleNamespace(post=Mock(return_value=body))
    with patch("openai.OpenAI", return_value=client):
        reasoner = OpenAIReasoner(OpenAIConfig("test", "vision", api_mode="responses"))
    device = Mock()
    device.screenshot.return_value = Image.new("RGB", (64, 64))
    result = Runner(device, reasoner, runs_dir=tmp_path).run(Task("test"))
    assert result.completed is False
    assert "reasoning_failed" in result.aborted_reason
    device.click.assert_not_called()
    client.post.assert_called_once()


@pytest.mark.parametrize("body", [
    [], {"status": "completed", "output": {}},
    {"status": "completed", "output": [], "error": {"code": "server_error"}},
    {"status": "completed", "output": [
        {"type": "message", "role": "assistant", "content": {}}]},
    {"status": "completed", "output": [
        {"type": "message", "role": "assistant", "status": "incomplete", "content": []}]},
])
def test_legacy_rejects_malformed_or_partial_json(body):
    with pytest.raises(ValueError):
        create_response(SimpleNamespace(post=Mock(return_value=body)), model="vision")


def test_legacy_text_aggregation_and_optional_usage():
    body = response_body("first")
    body["output"][-1]["content"].append({"type": "output_text", "text": " second"})
    body.pop("usage")
    response = create_response(SimpleNamespace(post=Mock(return_value=body)), model="vision")
    assert response.output_text == "first second"
    assert response.usage is None


@pytest.mark.parametrize("body", [
    {"status": "completed", "output": []},
    {"status": "completed", "output": [{"type": "message", "role": "assistant",
        "content": [{"type": "refusal", "refusal": "Refused"}]}]},
])
def test_legacy_empty_or_refused_response_aborts_runner(tmp_path, body):
    client = SimpleNamespace(post=Mock(return_value=body))
    with patch("openai.OpenAI", return_value=client):
        reasoner = OpenAIReasoner(OpenAIConfig("test", "vision", api_mode="responses"))
    device = Mock()
    device.screenshot.return_value = Image.new("RGB", (64, 64))
    result = Runner(device, reasoner, runs_dir=tmp_path).run(Task("test"))
    assert result.completed is False
    device.click.assert_not_called()


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 429, 500])
def test_legacy_http_errors_abort_without_switching_protocol(tmp_path, status_code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status_code, json={"error": {"message": "test failure"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with OpenAI(api_key="test", base_url="https://proxy.example/v1",
                    max_retries=0, http_client=http_client) as client:
            with patch("openai.OpenAI", return_value=SimpleNamespace(post=client.post)):
                reasoner = OpenAIReasoner(OpenAIConfig("test", "vision", api_mode="responses"))
            device = Mock()
            device.screenshot.return_value = Image.new("RGB", (64, 64))
            result = Runner(device, reasoner, runs_dir=tmp_path).run(Task("test"))
    assert result.completed is False
    expected_requests = 2 if status_code in (429, 500) else 1
    assert len(requests) == expected_requests
    assert all(request.url.path == "/v1/responses" for request in requests)
    device.click.assert_not_called()
