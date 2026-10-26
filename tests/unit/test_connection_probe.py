import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from openai import OpenAI

from seetouch.core.action import Action, ActionOutput
from seetouch.core.exceptions import VLMAPIError
from seetouch.reasoning.doubao import DoubaoConfig, DoubaoReasoner


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "android/app/src/main/python"))
    return importlib.import_module("seetouchapp.connection_test")


@pytest.mark.parametrize("mode", ["chat_completions", "responses"])
def test_probe_sends_fixed_synthetic_image_and_selected_protocol(probe, monkeypatch, mode):
    seen = []
    def handler(request):
        seen.append(request)
        body = json.loads(request.content)
        assert probe.TEST_QUESTION in str(body)
        assert "data:image/jpeg;base64," in str(body)  # 截图默认 JPEG
        if mode == "responses":
            assert request.url.path == "/v1/responses"
            return httpx.Response(200, json={"id": "resp", "status": "completed", "output": [
                {"type": "message", "role": "assistant", "content": [{"type": "output_text",
                    "text": '{"action":"COMPLETE","parameters":{}}'}]}]})
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
            "model": "vision", "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"action":"COMPLETE","parameters":{}}'}}]})
    client = OpenAI(api_key="test", base_url="https://probe.invalid/v1",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("openai.OpenAI", lambda **_: client)
    result = json.loads(probe.test_connection(json.dumps({"reasoner": "openai", "api_key": "test",
                                                        "model_id": "vision", "api_mode": mode})))
    assert result["success"] and result["elapsed_seconds"] >= 0
    assert len(seen) == 1 and client.is_closed()


@pytest.mark.parametrize("status,code,category", [
    (401, "invalid_api_key", "authentication"), (403, "permission_denied", "authentication"),
    (429, "insufficient_quota", "quota"), (402, "", "quota"),
    (404, "model_not_found", "model_not_found"), (429, "rate_limit_exceeded", "rate_limit"),
    (503, "", "server"),
])
def test_error_classes_are_safe_and_not_confused(probe, monkeypatch, status, code, category):
    error = RuntimeError("private-key-secret must not be displayed")
    error.status_code, error.body = status, {"error": {"code": code}}
    reasoner = Mock()
    reasoner.predict.side_effect = error
    monkeypatch.setattr(probe, "_create_reasoner", lambda _: reasoner)
    result = json.loads(probe.test_connection("{}"))
    assert result["category"] == category and not result["success"]
    assert "private-key-secret" not in json.dumps(result)
    reasoner._client.close.assert_called_once()


def test_network_cause_survives_reasoner_wrapping(probe):
    try:
        raise TimeoutError("secret")
    except TimeoutError as cause:
        try:
            raise VLMAPIError("wrapped") from cause
        except VLMAPIError as error:
            assert probe._classify(error)[0] == "network"


def test_unparsable_fallback_is_not_connection_success(probe, monkeypatch):
    reasoner = Mock()
    reasoner.predict.return_value = ActionOutput(Action("WAIT"), raw_output="not an action")
    monkeypatch.setattr(probe, "_create_reasoner", lambda _: reasoner)
    assert json.loads(probe.test_connection("{}"))["category"] == "unparsable"


def test_doubao_api_error_cannot_become_complete(monkeypatch):
    monkeypatch.setattr("openai.OpenAI", Mock())
    reasoner = DoubaoReasoner(DoubaoConfig("test"))
    reasoner._call_api = Mock(side_effect=TimeoutError("offline"))
    from PIL import Image
    with pytest.raises(VLMAPIError) as caught:
        reasoner.predict("test", Image.new("RGB", (10, 10)), [])
    assert isinstance(caught.value.__cause__, TimeoutError)


@pytest.mark.parametrize("mode", ["chat_completions", "responses"])
@pytest.mark.parametrize("status,code,category", [
    (401, "invalid_api_key", "authentication"), (429, "insufficient_quota", "quota"),
    (404, "model_not_found", "model_not_found"),
])
def test_http_errors_keep_their_categories_through_real_sdk(probe, monkeypatch, mode, status, code, category):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"error": {"message": "test", "code": code, "type": code}})
    client = OpenAI(api_key="test", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("openai.OpenAI", lambda **_: client)
    result = json.loads(probe.test_connection(json.dumps({"reasoner": "openai", "api_key": "test",
                                                        "model_id": "vision", "api_mode": mode})))
    assert result["category"] == category
    assert len(seen) == 1


@pytest.mark.parametrize("mode", ["chat_completions", "responses"])
def test_empty_success_response_is_reported_as_unparsable(probe, monkeypatch, mode):
    client = OpenAI(api_key="test", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))))
    monkeypatch.setattr("openai.OpenAI", lambda **_: client)
    result = json.loads(probe.test_connection(json.dumps({"reasoner": "openai", "api_key": "test",
                                                        "model_id": "vision", "api_mode": mode})))
    assert result["category"] == "unparsable"
