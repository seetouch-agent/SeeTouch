"""UI 节点模型：多来源归一化、渲染与签名。"""

from seetouch.harness.nodes import (
    UiNode,
    node_from_element,
    nodes_from_elements,
    nodes_from_rows,
    nodes_from_xml,
    nodes_signature,
    render_nodes,
)

XML = """<?xml version="1.0"?>
<hierarchy rotation="0">
  <node package="com.android.systemui" text="12:00" class="android.widget.TextView"
        clickable="false" scrollable="false" focused="false" bounds="[0,0][100,50]" />
  <node package="com.android.settings" text="深色主题" class="android.widget.TextView"
        clickable="true" scrollable="false" focused="false" bounds="[100,200][900,300]" />
  <node package="com.android.settings" text="" class="android.widget.EditText"
        clickable="true" scrollable="false" focused="true" bounds="[100,400][900,500]" />
  <node package="com.android.settings" text="" class="android.widget.FrameLayout"
        clickable="false" scrollable="false" focused="false" bounds="[0,0][0,0]" />
</hierarchy>
"""


def test_nodes_from_xml_normalises_bounds_and_flags():
    nodes = nodes_from_xml(XML, screen=(1000, 1000))
    assert [n.text for n in nodes] == ["深色主题", ""]
    first, second = nodes
    assert first.center((1000, 1000)) == (500, 250)
    assert first.clickable and not first.editable
    assert second.editable and second.focused
    assert second.center((1000, 1000)) == (500, 450)


def test_nodes_from_xml_skips_system_ui_and_zero_size():
    nodes = nodes_from_xml(XML, screen=(1000, 1000))
    assert all("12:00" != n.text for n in nodes)
    assert all(n.width > 0 and n.height > 0 for n in nodes)


def test_nodes_from_elements_accepts_flags_string_and_bools():
    nodes = nodes_from_elements([
        {"text": " 确定 ", "flags": "click,focus", "bounds": (0, 100, 200, 200)},
        {"text": "搜索", "clickable": True, "editable": True, "bounds": [0, 300, 200, 400]},
    ], screen=(1000, 1000))
    assert nodes[0].text == "确定" and nodes[0].clickable and nodes[0].focused
    assert nodes[1].clickable and nodes[1].editable


def test_node_cleans_quotes_and_collapses_whitespace():
    node = node_from_element({"text": 'a\n"b"   c', "bounds": [0, 0, 10, 10]})
    assert node.text == "a 'b' c"


def test_nodes_from_rows_reads_bridge_format():
    nodes = nodes_from_rows([
        "深色主题\t\tswitch_widget\tSwitch\t100\t200\t900\t300\tclick,scroll",
        "搜索\t\tsearch\tEditText\t100\t400\t900\t500\tedit,focus",
        "broken-row",
    ], screen=(1000, 1000))
    assert len(nodes) == 2
    assert nodes[0].center((1000, 1000)) == (500, 250)
    assert nodes[1].editable and nodes[1].focused


def test_render_nodes_respects_limits():
    nodes = [UiNode(text=f"项{i}", bounds=(0, i * 10, 100, i * 10 + 10)) for i in range(20)]
    text = render_nodes(nodes, (1000, 1000), limit=5)
    assert len(text.splitlines()) == 5
    assert "项0" in text and "项5" not in text

    truncated = render_nodes(nodes, (1000, 1000), limit=20, max_chars=40)
    assert len(truncated) == 40


def test_render_nodes_keeps_legacy_line_format():
    node = UiNode(text="设置", bounds=(100, 200, 900, 300), clickable=True)
    line = node.to_line((1000, 1000))
    assert line.startswith('- text="设置"')
    assert "center=[500,250]" in line
    assert "flags=click" in line


def test_signature_ignores_focus_but_tracks_content():
    base = UiNode(text="设置", bounds=(0, 0, 100, 100), clickable=True)
    focused = UiNode(text="设置", bounds=(0, 0, 100, 100), clickable=True, focused=True)
    other = UiNode(text="蓝牙", bounds=(0, 0, 100, 100), clickable=True)
    assert nodes_signature([base]) == nodes_signature([focused])
    assert nodes_signature([base]) != nodes_signature([other])
    assert nodes_signature([]) == ""
