"""观测对象：来源优先级、落点校准、界面签名。"""

from seetouch.harness.observation import Observation, build_observation
from seetouch.harness.nodes import UiNode


def _nodes():
    return [
        {"text": "深色主题", "bounds": (100, 200, 900, 300), "clickable": True},
        {"text": "搜索", "bounds": (100, 400, 900, 500), "editable": True, "focused": True},
    ]


def test_build_observation_prefers_elements_over_rows_and_xml():
    obs = build_observation(elements=_nodes(), rows=["忽略\t\t\t\t0\t0\t1\t1\tclick"],
                            xml_text="<hierarchy/>", screen_size=(1000, 1000))
    assert obs.source == "elements"
    assert [n.text for n in obs.nodes] == ["深色主题", "搜索"]
    assert obs.has_nodes
    assert obs.signature


def test_build_observation_falls_back_and_marks_empty():
    obs = build_observation(screen_size=(1000, 1000))
    assert obs.source == "none" and not obs.has_nodes
    assert obs.signature == ""
    assert obs.render() == ""


def test_ground_keeps_point_inside_a_clickable_node():
    obs = build_observation(elements=_nodes(), screen_size=(1000, 1000))
    point, node = obs.ground((520, 260))
    assert point == (520.0, 260.0)
    assert node is not None and node.text == "深色主题"


def test_ground_snaps_nearby_point_to_node_center():
    obs = build_observation(elements=_nodes(), screen_size=(1000, 1000))
    # 点在节点边缘外侧 30 个单位，仍在 60 的吸附半径内
    point, node = obs.ground((510, 305))
    assert point == (500.0, 250.0)
    assert node is not None and node.text == "深色主题"


def test_ground_leaves_far_points_alone():
    obs = build_observation(elements=_nodes(), screen_size=(1000, 1000))
    point, node = obs.ground((500, 900))
    assert point == (500.0, 900.0)
    assert node is None


def test_ground_without_nodes_is_a_noop():
    obs = Observation(screen_size=(1000, 1000))
    assert obs.ground((123, 456)) == ((123.0, 456.0), None)


def test_ground_respects_custom_radius():
    obs = build_observation(elements=_nodes(), screen_size=(1000, 1000))
    point, node = obs.ground((510, 305), radius=5)
    assert point == (510.0, 305.0) and node is None


def test_focused_and_editable_helpers():
    obs = build_observation(elements=_nodes(), screen_size=(1000, 1000))
    assert obs.focused_node is not None and obs.focused_node.text == "搜索"
    assert [n.text for n in obs.editable_nodes] == ["搜索"]
    assert len(obs.actionable_nodes) == 2


def test_render_uses_node_lines():
    obs = build_observation(elements=_nodes(), screen_size=(1000, 1000))
    text = obs.render()
    assert "深色主题" in text and "center=[500,250]" in text


def test_nodes_are_immutable():
    obs = Observation(nodes=(UiNode(text="a"),))
    assert isinstance(obs.nodes, tuple)
