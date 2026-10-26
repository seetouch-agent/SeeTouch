"""动作协议层：落点吸附与诊断。"""

from seetouch.core.action import ACTION_BACK, ACTION_CLICK, ACTION_LONG_PRESS, Action
from seetouch.harness.observation import build_observation
from seetouch.harness.protocol import ground_action, validate_action

ELEMENTS = [
    {"text": "深色主题", "bounds": (100, 200, 900, 300), "clickable": True},
    {"text": "搜索", "bounds": (100, 400, 900, 500), "editable": True},
]


def _observation():
    return build_observation(elements=ELEMENTS, screen_size=(1000, 1000))


def test_ground_moves_off_center_click_to_node_center():
    result = ground_action(Action(ACTION_CLICK, {"point": [510, 305]}), _observation())
    assert result.moved
    assert result.action.parameters["point"] == [500, 250]
    assert result.node is not None and result.node.text == "深色主题"
    assert "click_grounded" in result.note


def test_ground_keeps_click_already_inside_node():
    result = ground_action(Action(ACTION_CLICK, {"point": [520, 260]}), _observation())
    assert not result.moved
    assert result.action.parameters["point"] == [520, 260]
    assert result.node is not None


def test_ground_reports_off_target_without_changing_action():
    result = ground_action(Action(ACTION_CLICK, {"point": [500, 950]}), _observation())
    assert not result.moved
    assert result.action.parameters["point"] == [500, 950]
    assert "附近没有可点控件" in result.note


def test_ground_without_observation_is_noop():
    action = Action(ACTION_CLICK, {"point": [123, 456]})
    assert ground_action(action, None).action is action
    assert ground_action(action, _observation(), enabled=False).action is action


def test_ground_ignores_non_click_actions():
    action = Action(ACTION_BACK, {})
    assert ground_action(action, _observation()).action is action


def test_validate_reports_empty_area_and_range():
    obs = _observation()
    assert validate_action(Action(ACTION_CLICK, {"point": [500, 950]}), obs) == [
        "click_on_empty_area"
    ]
    assert "point_out_of_range" in validate_action(
        Action(ACTION_CLICK, {"point": [1200, 300]}), obs
    )
    assert validate_action(Action(ACTION_CLICK, {}), obs) == ["click_without_point"]


def test_validate_passes_for_grounded_click():
    assert validate_action(Action(ACTION_CLICK, {"point": [500, 250]}), _observation()) == []


def test_long_press_is_grounded_like_a_click():
    result = ground_action(Action(ACTION_LONG_PRESS, {"point": [510, 305]}), _observation())
    assert result.moved
    assert result.action.parameters["point"] == [500, 250]


def test_validate_reports_long_press_without_point():
    assert validate_action(Action(ACTION_LONG_PRESS, {}), _observation()) == [
        "long_press_without_point"
    ]
