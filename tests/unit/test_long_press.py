"""LONG_PRESS 动作:模型输出 -> Runner 分派 -> 设备层手势。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from seetouch.core.action import ACTION_COMPLETE, ACTION_LONG_PRESS, Action, ActionOutput
from seetouch.core.exceptions import DeviceError
from seetouch.core.runner import Runner
from seetouch.core.session import Session
from seetouch.core.task import Task
from seetouch.device.android.controller import LONG_PRESS_DURATION_S, AndroidController
from seetouch.device.android_native.controller import NativeAndroidController
from seetouch.reasoning.base import StepRecord


def test_long_press_requires_point():
    with pytest.raises(ValueError, match="LONG_PRESS requires parameters.point"):
        Action(type=ACTION_LONG_PRESS, parameters={}).validate()


def test_android_controller_long_press_converts_normalized_coords():
    controller = AndroidController.__new__(AndroidController)
    controller._d = MagicMock()
    controller._screen_size = (1000, 2000)

    controller.long_press(500, 250)

    controller._d.long_click.assert_called_once_with(
        500, 500, duration=LONG_PRESS_DURATION_S
    )


def test_native_controller_long_press_calls_bridge():
    controller = NativeAndroidController.__new__(NativeAndroidController)
    controller._b = SimpleNamespace(longClick=MagicMock(return_value=True))
    controller._screen_size = (1000, 2000)

    controller.long_press(500, 250)

    controller._b.longClick.assert_called_once_with(500, 500)


def test_native_controller_long_press_raises_when_gesture_rejected():
    controller = NativeAndroidController.__new__(NativeAndroidController)
    controller._b = SimpleNamespace(longClick=MagicMock(return_value=False))
    controller._screen_size = (1000, 2000)

    with pytest.raises(DeviceError, match="long_press"):
        controller.long_press(500, 250)


def test_runner_dispatches_long_press(tmp_path):
    outputs = [
        ActionOutput(action=Action(type=ACTION_LONG_PRESS, parameters={"point": [500, 820]})),
        ActionOutput(action=Action(type=ACTION_COMPLETE, parameters={})),
    ]

    class Reasoner:
        def predict(self, instruction, screenshot, history):
            return outputs.pop(0)

    device = MagicMock()
    device.screenshot.return_value = Image.new("RGB", (100, 200))
    device.ui_context.return_value = ""

    result = Runner(device, Reasoner(), runs_dir=tmp_path).run(
        Task("长按设置图标打开应用信息", task_id="long-press")
    )

    assert result.completed is True
    device.long_press.assert_called_once_with(500, 820)
    device.click.assert_not_called()


def test_jittered_long_presses_count_as_identical(tmp_path):
    session = Session(Task("test", task_id="lp-jitter"), tmp_path)
    for step, y in enumerate((820, 822, 825), start=1):
        session.history.append(StepRecord(
            step=step,
            action=Action(type=ACTION_LONG_PRESS, parameters={"point": [500, y]}),
        ))
    assert session.consecutive_identical_actions() == 3
