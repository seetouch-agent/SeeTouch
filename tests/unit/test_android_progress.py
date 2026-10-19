import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from seetouch.core.action import Action, ActionOutput
from seetouch.core.exceptions import VLMAPIError


@pytest.fixture
def entry(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[2] / "android/app/src/main/python/seetouchapp/task_entry.py"
    spec = importlib.util.spec_from_file_location("android_progress_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("com", "com.seetouch", "com.seetouch.app", "com.seetouch.app.bridge"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["com.seetouch.app.bridge"].DeviceBridge = SimpleNamespace(filesDir=lambda: tmp_path)
    device = Mock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    monkeypatch.setattr("seetouch.device.android_native.controller.NativeAndroidController",
                        lambda: device)
    monkeypatch.setattr("seetouch.core.runner.time.sleep", lambda _: None)
    return module, device


def test_real_runner_reports_phases_before_executing_and_keeps_legacy_callback(entry, monkeypatch):
    module, device = entry
    events, steps = [], []
    outputs = iter([
        ActionOutput(Action("CLICK", {"point": [500, 300]}), action_summary="打开搜索框"),
        ActionOutput(Action("COMPLETE")),
    ])

    def predict(*_):
        assert events[-1]["phase"] == "thinking"
        return next(outputs)

    device.click.side_effect = lambda *_: (
        events[-1]["phase"] == "executing" or pytest.fail("action preceded progress event")
    )
    monkeypatch.setattr(module, "_create_reasoner", lambda _: SimpleNamespace(predict=predict))
    result = json.loads(module.run_task("打开时钟", "{}", lambda s: steps.append(json.loads(s)),
                                       None, lambda s: events.append(json.loads(s))))
    assert result["completed"] is True
    assert [(e["step"], e["phase"]) for e in events] == [
        (0, "starting"), (1, "capturing"), (1, "thinking"), (1, "checking"), (1, "executing"),
        (2, "capturing"), (2, "thinking"), (2, "checking"),
    ]
    assert events[3]["action_summary"] == "打开搜索框"
    assert len(steps) == 2
    assert all(set(e) == {"step", "phase", "action", "action_summary"} for e in events)


def test_api_failure_does_not_report_execution_or_completion(entry, monkeypatch):
    module, device = entry
    events = []
    reasoner = Mock()
    reasoner.predict.side_effect = VLMAPIError("test failure")
    monkeypatch.setattr(module, "_create_reasoner", lambda _: reasoner)
    result = json.loads(module.run_task("test", "{}", progress_callback=lambda s: events.append(
        json.loads(s))))
    assert result["completed"] is False
    assert [e["phase"] for e in events] == ["starting", "capturing", "thinking"]
    device.click.assert_not_called()


@pytest.mark.parametrize("with_progress", [False, True])
def test_missing_or_broken_progress_observer_does_not_change_task(entry, monkeypatch, with_progress):
    module, _ = entry
    monkeypatch.setattr(module, "_create_reasoner", lambda _: SimpleNamespace(
        predict=lambda *_: ActionOutput(Action("COMPLETE"))))
    if with_progress:
        callback = Mock(side_effect=RuntimeError("display unavailable"))
        result = module.run_task("test", "{}", None, None, callback)
        assert callback.call_count > 0
    else:
        result = module.run_task("test", "{}", None, None)
    assert json.loads(result)["completed"] is True


@pytest.mark.parametrize("approved", [False, True])
def test_confirmation_happens_before_any_device_action(entry, monkeypatch, approved):
    module, device = entry
    events = []
    outputs = iter([
        ActionOutput(Action("CLICK", {"point": [500, 300]}), action_summary="确认发送"),
        ActionOutput(Action("COMPLETE")),
    ])
    monkeypatch.setattr(module, "_create_reasoner", lambda _: SimpleNamespace(
        predict=lambda *_: next(outputs)))

    def confirm(message):
        assert "确认发送" in message
        assert events[-1]["phase"] == "checking"
        device.click.assert_not_called()
        return approved

    result = json.loads(module.run_task("发送消息", "{}", None, confirm,
                                       lambda s: events.append(json.loads(s))))
    assert result["completed"] is approved
    if approved:
        device.click.assert_called_once()
    else:
        device.click.assert_not_called()
        assert "executing" not in [e["phase"] for e in events]


@pytest.mark.parametrize("kind", ["ASK_USER", "TAKE_OVER"])
def test_interaction_bridge_returns_to_fresh_observation(entry, monkeypatch, kind):
    module, device = entry
    prompts, requests, steps = [], [], []
    params = {"question": "选哪个？", "options": ["甲", "乙"]} if kind == "ASK_USER" else {"reason": "请登录"}
    revision = [0]
    def predict(instruction, *_):
        prompts.append(instruction)
        return ActionOutput(Action(kind, params)) if len(prompts) == 1 else ActionOutput(Action("COMPLETE"))
    reasoner = SimpleNamespace(predict=predict, _client=Mock())
    monkeypatch.setattr(module, "_create_reasoner", lambda _: reasoner)
    def interaction(request_json):
        requests.append(json.loads(request_json))
        assert device.screenshot.call_count == 1
        device.click.assert_not_called()
        revision[0] += 2
        return json.dumps({"status": "answered", "answer": "乙"} if kind == "ASK_USER" else {"status": "resumed"})
    result = json.loads(module.run_task("打开时钟", "{}", lambda x: steps.append(json.loads(x)), None, None,
        lambda _: json.dumps({"mode": "running", "revision": revision[0]}), interaction))
    assert result["completed"]
    assert requests == [{"type": kind, **params}]
    assert device.screenshot.call_count == 2
    if kind == "ASK_USER":
        assert "回答：乙" in prompts[1] and "回答：乙" in steps[0]["notes"][0]
    reasoner._client.close.assert_called_once()


def test_floating_entry_preserves_current_app_and_returns_answer_source(entry, monkeypatch):
    module, device = entry
    monkeypatch.setattr(module, "_create_reasoner", lambda _: SimpleNamespace(predict=lambda *_: ActionOutput(
        Action("ANSWER", {"answer": "当前页面的查询答案", "source_step": 1}))))
    result = json.loads(module.run_task("查询当前页面", '{"start_from_current":true,"task_id":"task_from_ball"}'))
    device.go_home.assert_not_called()
    assert result["task_id"] == "task_from_ball" and result["answer_source_step"] == 1
    assert result["answer"] == "当前页面的查询答案"
    assert result["answer_screenshot"].endswith("step_001.png")


def test_native_confirmation_timeout_json_is_denied_in_python(entry, monkeypatch):
    module, device = entry
    monkeypatch.setattr(module, "_create_reasoner", lambda _: SimpleNamespace(predict=lambda *_: ActionOutput(
        Action("CLICK", {"point": [500, 300]}), action_summary="确认发送消息")))
    result = json.loads(module.run_task("发送消息", "{}", None,
        lambda _: '{"approved":false,"choice":"timeout"}'))
    assert not result["completed"] and result["reason_code"] == "user_denied"
    device.click.assert_not_called()
