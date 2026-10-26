"""UI-tree grounding for the PC device path and Runner prompt."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image

from seetouch.core.action import ACTION_CLICK, ACTION_COMPLETE, Action, ActionOutput
from seetouch.core.runner import Runner
from seetouch.core.session import Session
from seetouch.core.task import Task
from seetouch.device.android.controller import AndroidController
from seetouch.device.android_native.controller import NativeAndroidController
from seetouch.reasoning.base import StepRecord


XML = """<?xml version="1.0"?>
<hierarchy rotation="0">
  <node package="com.android.systemui" text="12:00" class="android.widget.TextView"
        clickable="false" scrollable="false" focused="false" bounds="[0,0][100,50]" />
  <node package="com.android.settings" text="深色主题" class="android.widget.TextView"
        clickable="true" scrollable="false" focused="false" bounds="[100,200][900,300]" />
  <node package="com.android.settings" text="" class="android.widget.EditText"
        clickable="true" scrollable="false" focused="true" bounds="[100,400][900,500]" />
</hierarchy>
"""


def test_android_controller_ui_context_has_centers_and_skips_status_bar():
    controller = AndroidController.__new__(AndroidController)
    controller._d = SimpleNamespace(dump_hierarchy=lambda compressed=True: XML)
    controller._screen_size = (1000, 1000)
    text = controller.ui_context()
    assert "深色主题" in text
    assert "center=[500,250]" in text
    assert "flags=click" in text
    assert "focus" in text and "edit" in text
    assert "12:00" not in text


def test_runner_appends_ui_context_to_reasoner_instruction(tmp_path):
    seen = {}

    class Reasoner:
        def predict(self, instruction, screenshot, history):
            seen["instruction"] = instruction
            return ActionOutput(action=Action(type=ACTION_COMPLETE, parameters={}))

    device = MagicMock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    device.ui_context.return_value = '- text="设置" center=[500,200] flags=click'
    runner = Runner(device, Reasoner(), runs_dir=tmp_path)
    result = runner.run(Task("打开设置", task_id="ui-context"))
    assert result.completed
    assert "当前界面控件" in seen["instruction"]
    assert "center=[500,200]" in seen["instruction"]
    trace = (tmp_path / "ui-context" / "trace.jsonl").read_text(encoding="utf-8")
    assert '"ui_context": "- text=' in trace


def test_runner_flags_unchanged_screen_on_next_step(tmp_path):
    instructions = []

    class Reasoner:
        def predict(self, instruction, screenshot, history):
            instructions.append(instruction)
            if len(instructions) == 1:
                return ActionOutput(action=Action(type=ACTION_CLICK, parameters={"point": [500, 500]}))
            return ActionOutput(action=Action(type=ACTION_COMPLETE, parameters={}))

    device = MagicMock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    device.ui_context.return_value = '- text="设置" center=[500,500] flags=click'
    runner = Runner(device, Reasoner(), runs_dir=tmp_path)
    result = runner.run(Task("打开设置", task_id="no-change"))
    assert result.completed
    assert "当前界面与之前 2 步相同" in instructions[1]
    assert "任务进度：已完成 1 步" in instructions[1]
    trace = (tmp_path / "no-change" / "trace.jsonl").read_text(encoding="utf-8")
    assert '"screen_unchanged_streak": 2' in trace


def test_native_controller_formats_bridge_nodes():
    controller = NativeAndroidController.__new__(NativeAndroidController)
    controller._b = SimpleNamespace(uiNodes=lambda: [
        "深色主题\t\tswitch_widget\tSwitch\t100\t200\t900\t300\tclick,scroll",
        "搜索\t\tsearch\tEditText\t100\t400\t900\t500\tedit,focus",
    ])
    controller._screen_size = (1000, 1000)
    text = controller.ui_context()
    assert "center=[500,250]" in text
    assert "flags=edit,focus" in text


def test_jittered_clicks_count_as_identical(tmp_path):
    session = Session(Task("test", task_id="jitter"), tmp_path)
    for step, y in enumerate((290, 292, 289), start=1):
        session.history.append(StepRecord(
            step=step,
            action=Action(type=ACTION_CLICK, parameters={"point": [500, y]}),
        ))
    assert session.consecutive_identical_actions() == 3


def test_parse_error_feedback_enters_history(tmp_path):
    session = Session(Task("test", task_id="parse"), tmp_path)
    out = ActionOutput(
        action=Action(type="WAIT", parameters={}),
        raw_output="not json at all",
        parse_error=True,
    )
    record = session.record_step(1, out, execution_success=None)
    assert any("不是合法动作 JSON" in note for note in record.notes)
    assert any("not json at all" in note for note in record.notes)


def test_multi_step_task_rejects_completion_right_after_open(tmp_path):
    outputs = [
        ActionOutput(action=Action(type="OPEN", parameters={"app_name": "设置"})),
        ActionOutput(action=Action(type=ACTION_COMPLETE, parameters={})),
        ActionOutput(action=Action(type=ACTION_COMPLETE, parameters={})),
    ]

    class Reasoner:
        def predict(self, instruction, screenshot, history):
            return outputs.pop(0)

    device = MagicMock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    result = Runner(device, Reasoner(), runs_dir=tmp_path).run(
        Task("打开设置，进入显示，开启深色主题，然后返回首页", task_id="premature")
    )
    assert result.completed is False
    assert result.aborted_reason == "premature_completion"
    trace = (tmp_path / "premature" / "trace.jsonl").read_text(encoding="utf-8")
    assert "拒绝过早完成" in trace


def test_single_step_task_accepts_completion_after_open(tmp_path):
    outputs = [
        ActionOutput(action=Action(type="OPEN", parameters={"app_name": "设置"})),
        ActionOutput(action=Action(type=ACTION_COMPLETE, parameters={})),
    ]

    class Reasoner:
        def predict(self, instruction, screenshot, history):
            return outputs.pop(0)

    device = MagicMock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    result = Runner(device, Reasoner(), runs_dir=tmp_path).run(
        Task("打开手机设置", task_id="simple")
    )
    assert result.completed is True
