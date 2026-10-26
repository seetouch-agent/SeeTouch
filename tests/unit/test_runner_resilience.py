"""Runner execution-budget, retry, and trace metadata tests."""

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image

from seetouch.core.action import ACTION_COMPLETE, Action, ActionOutput
from seetouch.core.exceptions import VLMAPIError
from seetouch.core.runner import Runner
from seetouch.core.task import Task


def _device():
    device = MagicMock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    device.current_app.return_value = None
    return device


def _complete():
    return ActionOutput(
        action=Action(type=ACTION_COMPLETE, parameters={}),
        raw_output='{"action":"COMPLETE","parameters":{}}',
    )


def test_task_timeout_is_terminal_and_classified(tmp_path):
    reasoner = MagicMock()
    runner = Runner(
        _device(), reasoner, runs_dir=tmp_path,
        task_timeout_seconds=0.01, max_model_retries=0,
    )
    task = Task("open settings", task_id="timeout-task")
    runner.start(task)
    time.sleep(0.02)
    result = runner.step()
    assert result.terminal
    assert result.terminal_reason == "task_timeout"
    runner.session.summarize()
    summary = json.loads((tmp_path / task.task_id / "summary.json").read_text(encoding="utf-8"))
    assert summary["completed"] is False
    assert summary["reason_code"] == "timeout"


def test_transient_api_error_retries_then_succeeds(tmp_path):
    rate_limited = VLMAPIError("429")
    rate_limited.status_code = 429
    reasoner = MagicMock()
    reasoner._config = SimpleNamespace(model_id="vision-test")
    reasoner.predict.side_effect = [rate_limited, _complete()]
    runner = Runner(
        _device(), reasoner, runs_dir=tmp_path,
        max_model_retries=1, model_retry_backoff_seconds=0,
    )
    task = Task("open settings", task_id="retry-task")
    result = runner.run(task)
    assert result.completed is True
    assert reasoner.predict.call_count == 2
    interactions = (tmp_path / task.task_id / "interactions.jsonl").read_text(encoding="utf-8")
    assert '"type": "model_retry"' in interactions
    trace = json.loads((tmp_path / task.task_id / "trace.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert trace["task_id"] == "retry-task"
    assert trace["model_id"] == "vision-test"
    assert trace["reasoner"] == "MagicMock"


def test_auth_error_is_not_retried(tmp_path):
    denied = VLMAPIError("401")
    denied.status_code = 401
    reasoner = MagicMock()
    reasoner.predict.side_effect = denied
    result = Runner(
        _device(), reasoner, runs_dir=tmp_path,
        max_model_retries=3, model_retry_backoff_seconds=0,
    ).run(Task("open settings", task_id="auth-task"))
    assert result.completed is False
    assert result.reason_code == "permission_missing"
    assert reasoner.predict.call_count == 1
