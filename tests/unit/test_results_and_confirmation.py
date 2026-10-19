import json
from unittest.mock import Mock

import pytest
from PIL import Image

from seetouch.core.action import Action, ActionOutput
from seetouch.core.exceptions import VLMAPIError
from seetouch.core.runner import Runner
from seetouch.core.task import Task
from seetouch.reasoning.parser import parse_model_output
from seetouch.safety.guard import Guard


def device():
    d = Mock()
    d.screenshot.return_value = Image.new("RGB", (100, 200), "white")
    d.takeover_reason.return_value = None
    return d


@pytest.mark.parametrize("action_type", ["ANSWER", "COMPLETE"])
def test_structured_answer_is_terminal_and_links_to_actual_screenshot(tmp_path, action_type):
    action = parse_model_output(json.dumps({"action": action_type, "parameters": {
        "answer": "明天晴，最高 26 度", "source_step": 1}}), (100, 200))
    d = device()
    runner = Runner(d, Mock(predict=lambda *_: ActionOutput(action)), runs_dir=tmp_path)
    result = runner.run(Task("查询天气"))
    assert result.completed and result.answer == "明天晴，最高 26 度"
    assert result.answer_source_step == 1
    assert result.answer_screenshot == str(runner.session.dir / "step_001.png")
    assert result.elapsed_seconds >= 0
    d.click.assert_not_called()
    saved = json.loads(runner.session.summary_path.read_text(encoding="utf-8"))
    assert saved["answer"] == result.answer


def test_invalid_answer_source_does_not_invent_evidence(tmp_path):
    runner = Runner(device(), Mock(predict=lambda *_: ActionOutput(Action("ANSWER", {
        "answer": "查询结果", "source_step": 99}))), runs_dir=tmp_path)
    result = runner.run(Task("查询天气"))
    assert result.answer == "查询结果"
    assert result.answer_screenshot is None and result.answer_source_step is None


def test_model_declared_failure_never_marks_task_complete(tmp_path):
    action = parse_model_output(json.dumps({"action": "COMPLETE", "parameters": {
        "status": "failed", "reason": "model_unable"}}), (100, 200))
    runner = Runner(device(), Mock(predict=lambda *_: ActionOutput(action)), runs_dir=tmp_path)
    result = runner.run(Task("完成任务"))
    assert not result.completed and result.reason_code == "model_unable"


@pytest.mark.parametrize("approved,choice", [(True, "allow"), (False, "deny")])
def test_structured_confirmation_contains_target_and_audits_choice(tmp_path, approved, choice):
    requests = []
    def confirm(request):
        requests.append(request)
        return {"approved": approved, "choice": choice}
    outputs = iter([ActionOutput(Action("CLICK", {"point": [500, 200]}), action_summary="确认发送消息"),
                    ActionOutput(Action("COMPLETE"))])
    d = device()
    runner = Runner(d, Mock(predict=lambda *_: next(outputs)), runs_dir=tmp_path,
                    guard=Guard(request_fn=confirm), action_settle_seconds=0)
    result = runner.run(Task("发送消息给指定联系人"))
    assert result.completed is approved
    assert requests[0]["parameters"]["point"] == [500, 200]
    assert "发送" in requests[0]["consequences"]
    assert requests[0]["screenshot_path"].endswith("step_001.png")
    events = [json.loads(x) for x in (runner.session.dir / "interactions.jsonl").read_text(encoding="utf-8").splitlines()]
    event = next(x for x in events if x["type"] == "confirmation")
    assert event["choice"] == choice and event["approved"] is approved and event["decided_at"] > 0
    assert d.click.call_count == int(approved)


@pytest.mark.parametrize("status,body,code", [(429, {"code": "insufficient_quota"}, "quota"),
                                             (403, {}, "permission_missing")])
def test_api_categories_survive_exception_chain_and_reach_result(tmp_path, status, body, code):
    cause = RuntimeError("provider detail")
    cause.status_code, cause.body = status, body
    def predict(*_):
        raise VLMAPIError("wrapped") from cause
    result = Runner(device(), Mock(predict=predict), runs_dir=tmp_path).run(Task("完成任务"))
    assert not result.completed and result.reason_code == code
