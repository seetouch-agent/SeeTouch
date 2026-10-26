"""用户输入保真：ASK_USER 的回答永不丢失、不重复，且排在历史之前。"""

from PIL import Image

from seetouch.core.action import ACTION_ASK_USER, ACTION_COMPLETE, Action, ActionOutput
from seetouch.core.runner import Runner
from seetouch.core.task import Task


class FakeDevice:
    def __init__(self):
        self.clicks = []

    def screenshot(self):
        return Image.new("RGB", (100, 200))

    def screen_size(self):
        return (1000, 2000)

    def ui_context(self):
        return '- text="设置" center=[500,200] flags=click'

    def click(self, x, y):
        self.clicks.append((x, y))

    def type_text(self, text):
        pass

    def scroll(self, start, end):
        pass

    def open_app(self, name):
        pass

    def back(self):
        pass

    def current_app(self):
        return None


class Reasoner:
    def __init__(self):
        self.instructions = []

    def predict(self, instruction, screenshot, history):
        self.instructions.append(instruction)
        if len(self.instructions) == 1:
            return ActionOutput(action=Action(
                ACTION_ASK_USER,
                {"question": "选哪个?", "options": ["第一个", "第二个"]},
            ))
        return ActionOutput(action=Action(ACTION_COMPLETE, {}))


def test_user_answer_is_injected_into_every_later_step(tmp_path):
    device = FakeDevice()
    reasoner = Reasoner()
    runner = Runner(
        device, reasoner, runs_dir=tmp_path,
        interaction=lambda request: {"status": "answered", "answer": "第二个"},
    )
    result = runner.run(Task("把设置改成夜间模式", task_id="pinned"))

    assert result.completed
    assert len(reasoner.instructions) == 2
    second = reasoner.instructions[1]
    assert "用户明确要求" in second
    assert "回答：第二个" in second
    # 用户补充排在进度与当前界面控件之前，模型先看到"用户要求"再看屏幕
    assert second.index("回答：第二个") < second.index("当前界面控件")


def test_pinned_inputs_are_deduplicated(tmp_path):
    device = FakeDevice()
    reasoner = Reasoner()
    runner = Runner(
        device, reasoner, runs_dir=tmp_path,
        interaction=lambda request: {"status": "answered", "answer": "第二个"},
    )
    runner.run(Task("把设置改成夜间模式", task_id="pinned-dedupe"))
    assert len(runner.pinned_inputs) == 1
    assert runner.pinned_inputs.render().count("回答：第二个") == 1


def test_non_interactive_host_stops_instead_of_guessing(tmp_path):
    device = FakeDevice()
    reasoner = Reasoner()
    runner = Runner(device, reasoner, runs_dir=tmp_path)
    result = runner.run(Task("把设置改成夜间模式", task_id="pinned-none"))
    assert not result.completed
    assert result.aborted_reason in ("interaction_unavailable", "user_denied")
