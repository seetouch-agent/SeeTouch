import json
import threading
import time
from unittest.mock import Mock

import pytest
from PIL import Image

from seetouch.core.action import Action, ActionOutput
from seetouch.core.control import ExecutionControl
from seetouch.core.runner import Runner
from seetouch.core.task import Task
from seetouch.reasoning.parser import parse_model_output
from seetouch.core.exceptions import ParseError


def wait_for(predicate, timeout=2):
    until = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < until, "worker did not reach expected state"
        time.sleep(0.005)


@pytest.fixture
def running_task(tmp_path):
    workers = []

    def start(predict, interaction=None, before_start=None):
        control = ExecutionControl()
        device = Mock()
        device.screenshot.side_effect = lambda: Image.new("RGB", (100, 200))
        device.takeover_reason.return_value = None
        reasoner = Mock(predict=Mock(side_effect=predict))
        runner = Runner(device, reasoner, runs_dir=tmp_path, control=control,
                        interaction=interaction, action_settle_seconds=0)
        runner.start(Task("打开时钟", max_steps=20))
        results, errors = [], []
        release = threading.Event()

        def work():
            try:
                results.append(runner.step())
            except BaseException as exc:
                errors.append(exc)

        if before_start:
            before_start(control, device, runner)
        worker = threading.Thread(target=work, daemon=True)
        workers.append((worker, control, release))
        worker.start()
        return runner, device, reasoner, control, results, errors, worker, release

    yield start
    for worker, control, release in workers:
        control.set_mode("stopped")
        release.set()
        worker.join(2)


@pytest.mark.parametrize("mode", ["paused", "takeover", "waiting_user"])
def test_no_capture_or_request_while_suspended(running_task, mode):
    def complete(*_):
        return ActionOutput(Action("COMPLETE"))
    _, device, model, control, results, errors, worker, _ = running_task(
        complete, before_start=lambda c, *_: c.set_mode(mode))
    time.sleep(0.12)
    device.screenshot.assert_not_called()
    model.predict.assert_not_called()
    control.set_mode("running")
    worker.join(2)
    assert not worker.is_alive() and not errors
    assert results[0].terminal_reason == "completed"


@pytest.mark.parametrize("cycles", [1, 10])
def test_pause_discards_stale_click_retains_response_and_reobserves(running_task, cycles):
    ready, release = threading.Event(), threading.Event()
    calls = []

    def predict(*_):
        calls.append(1)
        if len(calls) == 1:
            ready.set()
            assert release.wait(2)
            return ActionOutput(Action("CLICK", {"point": [100, 200]}), raw_output="old decision",
                                usage={"input_tokens": 5, "output_tokens": 3})
        return ActionOutput(Action("COMPLETE"), usage={"input_tokens": 7, "output_tokens": 2})

    runner, device, _, control, results, errors, worker, _ = running_task(predict)
    try:
        assert ready.wait(1)
        for _ in range(cycles):
            control.set_mode("paused")
            control.set_mode("running")
        control.set_mode("paused")
        release.set()
        wait_for(lambda: (runner.session.dir / "interactions.jsonl").exists())
        device.click.assert_not_called()
        assert worker.is_alive()
        assert device.screenshot.call_count == 1
        control.set_mode("running")
        worker.join(2)
        assert not worker.is_alive() and not errors
        assert results[0].terminal_reason == "completed"
        assert device.screenshot.call_count == 2
        device.click.assert_not_called()
        held = [json.loads(x) for x in (runner.session.dir / "interactions.jsonl").read_text(encoding="utf-8").splitlines()]
        pending = next(event for event in held if event["type"] == "held_decision")
        assert pending["raw_output"] == "old decision" and not pending["executed"]
        assert (runner.session.dir / "step_001_retry_1.png").exists()
        summary = runner.session.summarize()
        assert (summary.total_input_tokens, summary.total_output_tokens) == (12, 5)
    finally:
        release.set()


def test_stop_during_request_never_executes_returned_action(running_task):
    ready, release = threading.Event(), threading.Event()

    def predict(*_):
        ready.set()
        assert release.wait(2)
        return ActionOutput(Action("CLICK", {"point": [500, 500]}))

    runner, device, _, control, results, errors, worker, _ = running_task(predict)
    try:
        assert ready.wait(1)
        started = time.monotonic()
        control.set_mode("stopped")
        assert time.monotonic() - started < 1
        release.set()
        worker.join(2)
        assert not errors and not worker.is_alive()
        assert results[0].terminal_reason == "user_stopped"
        assert not runner.session.summarize().completed
        device.click.assert_not_called()
    finally:
        release.set()


def test_automatic_takeover_precedes_first_screenshot(running_task):
    interactions = []

    def before(control, device, runner):
        device.takeover_reason.side_effect = ["需要密码", None]
        def interact(request):
            device.screenshot.assert_not_called()
            interactions.append(request)
            return {"status": "resumed"}
        runner.interaction = interact

    runner, device, model, _, results, errors, worker, _ = running_task(
        lambda *_: ActionOutput(Action("COMPLETE")), before_start=before)
    worker.join(2)
    assert not errors
    assert interactions == [{"type": "TAKE_OVER", "reason": "需要密码"}]
    assert device.screenshot.call_count == model.predict.call_count == 1
    assert results[0].terminal
    assert "sensitive_screen" in (runner.session.dir / "interactions.jsonl").read_text(encoding="utf-8")


def test_question_answer_persists_in_context_and_step_log(tmp_path):
    device = Mock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    device.takeover_reason.return_value = None
    received = []
    def predict(instruction, *_):
        received.append(instruction)
        return ActionOutput(Action("ASK_USER", {"question": "选哪一个？", "options": ["甲", "乙"]})) \
            if len(received) == 1 else ActionOutput(Action("COMPLETE"))
    runner = Runner(device, Mock(predict=predict), runs_dir=tmp_path,
                    interaction=lambda _: {"status": "answered", "answer": "乙"})
    result = runner.run(Task("打开时钟"))
    assert result.completed
    assert "选哪一个？" in received[1] and "回答：乙" in received[1]
    trace = [json.loads(x) for x in runner.session.trace_path.read_text(encoding="utf-8").splitlines()]
    assert "回答：乙" in trace[0]["notes"][0]
    assert trace[0]["interactions"][-1]["type"] == "user_answer"
    device.click.assert_not_called()


@pytest.mark.parametrize("action,params", [
    ("ASK_USER", {"question": "选择哪个？", "options": ["A", "B"]}),
    ("TAKE_OVER", {"reason": "请完成登录"}),
])
def test_interaction_protocol(action, params):
    parsed = parse_model_output(json.dumps({"action": action, "parameters": params}), (100, 200))
    parsed.validate()
    assert parsed.type == action and parsed.parameters == params


@pytest.mark.parametrize("params", [{}, {"question": ""}, {"question": "Q", "options": "A"}])
def test_invalid_questions_rejected(params):
    with pytest.raises(ParseError):
        parse_model_output(json.dumps({"action": "ASK_USER", "parameters": params}), (100, 200))


def test_invalid_question_cannot_fall_back_to_a_device_action_embedded_in_text():
    with pytest.raises(ParseError):
        parse_model_output('{"action":"ASK_USER","parameters":{"question":"TYPE: secret","options":"bad"}}', (100, 200))
