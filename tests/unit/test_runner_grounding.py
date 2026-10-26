"""Runner 与 harness 的集成：点击落点校准、界面签名、空转终止。"""

from PIL import Image

from seetouch.core.action import ACTION_CLICK, ACTION_COMPLETE, Action, ActionOutput
from seetouch.core.runner import Runner
from seetouch.core.task import Task


ELEMENTS = [
    {"text": "深色主题", "bounds": (100, 200, 900, 300), "clickable": True},
    {"text": "自动设置时间", "bounds": (100, 600, 900, 700), "clickable": True},
]


class FakeDevice:
    """只实现 Runner 需要的那部分 DeviceController。"""

    def __init__(self, elements=None, screen=(1000, 1000)):
        self.elements = elements if elements is not None else list(ELEMENTS)
        self._screen = screen
        self.clicks: list[tuple[int, int]] = []

    def screenshot(self):
        return Image.new("RGB", (1080, 1920), (20, 20, 20))

    def screen_size(self):
        return self._screen

    def ui_elements(self):
        return list(self.elements)

    def ui_context(self):
        return "- text=\"深色主题\" center=[500,250] flags=click"

    def click(self, x, y):
        self.clicks.append((int(x), int(y)))

    def type_text(self, text):
        pass

    def scroll(self, start, end):
        pass

    def open_app(self, name):
        pass

    def back(self):
        pass

    def current_app(self):
        return "com.android.settings"


class ScriptedReasoner:
    def __init__(self, actions):
        self.actions = list(actions)
        self.instructions: list[str] = []

    def predict(self, instruction, screenshot, history):
        self.instructions.append(instruction)
        action = self.actions.pop(0) if self.actions else Action(ACTION_COMPLETE, {})
        return ActionOutput(action=action)


def test_off_center_click_is_snapped_to_real_control(tmp_path):
    device = FakeDevice()
    reasoner = ScriptedReasoner([Action(ACTION_CLICK, {"point": [510, 305]})])
    runner = Runner(device, reasoner, runs_dir=tmp_path)
    result = runner.run(Task("打开深色主题", task_id="ground"))

    assert result.completed
    # 模型点 (450,330)，吸附到控件中心 (500,250)
    assert device.clicks == [(500, 250)]
    trace = (tmp_path / "ground" / "trace.jsonl").read_text()
    assert "click_grounded" in trace


def test_grounding_can_be_disabled(tmp_path):
    device = FakeDevice()
    reasoner = ScriptedReasoner([Action(ACTION_CLICK, {"point": [510, 305]})])
    runner = Runner(device, reasoner, runs_dir=tmp_path, enable_click_grounding=False)
    runner.run(Task("打开深色主题", task_id="no-ground"))
    assert device.clicks == [(510, 305)]


def test_click_inside_control_is_left_alone(tmp_path):
    device = FakeDevice()
    reasoner = ScriptedReasoner([Action(ACTION_CLICK, {"point": [520, 260]})])
    runner = Runner(device, reasoner, runs_dir=tmp_path)
    runner.run(Task("打开深色主题", task_id="inside"))
    assert device.clicks == [(520, 260)]


def test_idle_screen_aborts_after_idle_budget(tmp_path):
    device = FakeDevice()  # ui_elements 恒定 → 界面签名永远不变
    reasoner = ScriptedReasoner([
        Action(ACTION_CLICK, {"point": [500, 250]}),
        Action(ACTION_CLICK, {"point": [500, 650]}),
        Action(ACTION_CLICK, {"point": [500, 250]}),
        Action(ACTION_CLICK, {"point": [500, 650]}),
    ])
    runner = Runner(device, reasoner, runs_dir=tmp_path, max_idle_steps=3)
    result = runner.run(Task("打开深色主题", task_id="idle"))

    assert not result.completed
    assert result.terminal_reason == "idle_exhausted"
    assert len(device.clicks) <= 3


def test_no_elements_keeps_legacy_behaviour(tmp_path):
    device = FakeDevice(elements=[])
    reasoner = ScriptedReasoner([Action(ACTION_CLICK, {"point": [510, 305]})])
    runner = Runner(device, reasoner, runs_dir=tmp_path)
    result = runner.run(Task("打开设置", task_id="no-nodes"))
    assert result.completed
    # 没有结构信息就不校准
    assert device.clicks == [(510, 305)]


def test_ledger_records_grounding_note(tmp_path):
    device = FakeDevice()
    reasoner = ScriptedReasoner([Action(ACTION_CLICK, {"point": [510, 305]})])
    runner = Runner(device, reasoner, runs_dir=tmp_path)
    runner.run(Task("打开深色主题", task_id="ledger"))
    snapshot = runner.ledger.snapshot()
    assert snapshot["steps"] == 1  # 只有执行型动作入账
    assert "click_grounded" in snapshot["entries"][0]["note"]
