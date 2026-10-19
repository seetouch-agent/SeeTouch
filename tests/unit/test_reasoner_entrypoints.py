import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from openai import OpenAI
from PIL import Image

from seetouch.cli.main import _build_parser
from seetouch.reasoning.factory import create_reasoner
from seetouch.reasoning.openai import OpenAIConfig, OpenAIReasoner


def test_entrypoint_defaults_remain_unchanged():
    parser = _build_parser()
    assert parser.parse_args(["run", "test"]).reasoner == "gemini"
    assert parser.parse_args(["debug"]).reasoner == "doubao"
    assert parser.parse_args(["debug", "--reasoner", "openai"]).reasoner == "openai"


def test_openai_does_not_reuse_legacy_provider_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("VLM_API_KEY", "legacy-key")
    monkeypatch.setenv("DOUBAO_API_URL", "https://legacy.example/v3")
    monkeypatch.setenv("OPENAI_MODEL_ID", "vision")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_reasoner("openai")


@pytest.mark.parametrize("mode", ["chat_completions", "responses"])
@pytest.mark.parametrize("effort", [None, "high", "none"])
def test_reasoning_effort_serialized_for_selected_protocol(mode, effort):
    def handler(request):
        payload = json.loads(request.content)
        assert "thinking" not in payload
        if mode == "responses":
            assert "reasoning_effort" not in payload
            assert payload.get("reasoning") == ({"effort": effort} if effort else None)
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 0,
                "model": "vision", "status": "completed", "usage": None,
                "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text",
                            "text": '{"action":"COMPLETE","parameters":{}}',
                            "annotations": []}]}],
            })
        assert "reasoning" not in payload
        assert payload.get("reasoning_effort") == effort
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "vision",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"action":"COMPLETE","parameters":{}}',
            }}], "usage": None,
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with OpenAI(api_key="test", http_client=http_client) as client:
            with patch("openai.OpenAI", return_value=client):
                reasoner = OpenAIReasoner(OpenAIConfig(
                    "test", "vision", api_mode=mode, reasoning_effort=effort,
                ))
            assert reasoner.predict("test", Image.new("RGB", (10, 10)), []).action.type == "COMPLETE"


def test_effort_validation_and_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_MODEL_ID", "vision")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", " HIGH ")
    assert OpenAIConfig.from_env().reasoning_effort == "high"
    with pytest.raises(ValueError, match="REASONING_EFFORT"):
        OpenAIConfig("test", "vision", reasoning_effort="invalid")


@pytest.fixture
def android_entry():
    path = Path(__file__).resolve().parents[2] / "android/app/src/main/python/seetouchapp/task_entry.py"
    spec = importlib.util.spec_from_file_location("android_task_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("thinking", ["enabled", "disabled", "auto"])
def test_android_legacy_config_keeps_doubao_and_thinking(android_entry, thinking):
    with patch("seetouch.reasoning.doubao.DoubaoReasoner") as constructor:
        android_entry._create_reasoner({"api_key": "legacy-key", "thinking_mode": thinking})
    config = constructor.call_args.args[0]
    assert config.api_key == "legacy-key"
    assert config.api_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert config.thinking_mode == thinking


def test_android_openai_requires_explicit_model_and_uses_chat(android_entry):
    with patch("openai.OpenAI", return_value=Mock()):
        with pytest.raises(ValueError, match="MODEL_ID"):
            android_entry._create_reasoner({"reasoner": "openai", "api_key": "test"})
        reasoner = android_entry._create_reasoner({
            "reasoner": "openai", "api_key": "test", "model_id": "vision",
            "base_url": "https://proxy.example/v1", "reasoning_effort": "low",
        })
    assert isinstance(reasoner, OpenAIReasoner)
    assert reasoner._config.api_mode == "chat_completions"
    assert reasoner._config.reasoning_effort == "low"


@pytest.mark.parametrize("mode", ["chat_completions", "responses"])
def test_android_passes_protocol_timeout_and_effort(android_entry, mode):
    with patch("openai.OpenAI", return_value=Mock()) as constructor:
        reasoner = android_entry._create_reasoner({
            "reasoner": "openai", "api_key": " test-key ", "model_id": " vision ",
            "base_url": "https://proxy.example/custom/v1/", "api_mode": mode,
            "timeout": 120, "reasoning_effort": "high",
        })
    assert reasoner._config.api_mode == mode
    assert reasoner._config.reasoning_effort == "high"
    constructor.assert_called_once_with(
        api_key="test-key", base_url="https://proxy.example/custom/v1",
        timeout=120.0, max_retries=1,
    )
    assert reasoner._config.model_id == "vision"


def test_debugger_passes_selected_backend_to_factory(tmp_path):
    pytest.importorskip("flask_socketio")
    from seetouch.config import AppSettings
    from seetouch.debugger.app import create_app

    settings = AppSettings(device_serial=None, runs_dir=tmp_path, max_steps=45, log_level="INFO")
    with patch("seetouch.debugger.app.create_reasoner", side_effect=ValueError("test stop")) as factory:
        with patch("seetouch.debugger.app.AndroidController"):
            app, socket = create_app(settings, reasoner_name="openai")
            client = socket.test_client(app)
            try:
                client.emit("start", {"instruction": "test"})
                factory.assert_called_once_with("openai")
            finally:
                client.disconnect()


@pytest.mark.parametrize("provider", ["doubao", "openai"])
def test_android_diagnostic_uses_explicit_provider(monkeypatch, provider):
    path = Path(__file__).resolve().parents[2] / "android/app/src/main/python"
    monkeypatch.syspath_prepend(str(path))
    from seetouchapp.selftest import _check_inference

    reasoner = Mock()
    reasoner.predict.return_value.raw_output = "{}"
    reasoner.predict.return_value.usage = {}
    with patch("seetouchapp.task_entry._create_reasoner", return_value=reasoner) as factory:
        if provider == "doubao":
            _check_inference("legacy-key", "", "")
        else:
            _check_inference("new-key", "https://proxy.example/v1", "vision", "openai")
    assert factory.call_args.args[0]["reasoner"] == provider
    if provider == "doubao":
        assert factory.call_args.args[0]["base_url"] == ""
