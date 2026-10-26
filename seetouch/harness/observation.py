"""观测对象：一帧屏幕的结构化快照 + 点击落点校准。

原来的主循环里，界面文本、截图哈希、点击坐标是三份各自生长的数据：模型给的坐标
没人校验，界面是否变化靠文本或像素的临时哈希，追查失败原因时还得回到 trace 里拼。

``Observation`` 把它们收进一个对象：

- ``nodes``：这一帧的控件列表（可能为空，纯视觉设备也工作）；
- ``signature``：结构签名，动作后重算一次就能判断"界面到底变没变"；
- ``screen_size``：坐标换算的唯一依据；
- ``ground``：把模型给的归一化点击点吸附到最近的可点控件中心。

第三条是这次升级的核心：模型经常给出"差一点点"的坐标（点到图标边缘、点到列表
间隙），点击落空后又被判成"界面未变化"，于是陷入重复点击。把落点吸附到真实控件
上，等于用设备提供的结构信息给坐标兜底。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .nodes import (
    UiNode,
    nodes_from_elements,
    nodes_from_rows,
    nodes_from_xml,
    render_nodes,
)

# 吸附半径（0-1000 归一化网格）：60 ≈ 屏幕宽度的 6%。
# 小于这个距离才算"想点这个控件"，再远就说明模型在看另一个目标，不该替它改主意。
DEFAULT_GROUNDING_RADIUS = 60.0


@dataclass(frozen=True)
class Observation:
    """一帧界面观测。"""

    nodes: tuple[UiNode, ...] = ()
    screen_size: tuple[int, int] = (0, 0)
    signature: str = ""
    source: str = "none"
    foreground: str | None = None

    @property
    def has_nodes(self) -> bool:
        return bool(self.nodes)

    @property
    def actionable_nodes(self) -> tuple[UiNode, ...]:
        return tuple(n for n in self.nodes if n.actionable)

    @property
    def focused_node(self) -> UiNode | None:
        for node in self.nodes:
            if node.focused:
                return node
        return None

    @property
    def editable_nodes(self) -> tuple[UiNode, ...]:
        return tuple(n for n in self.nodes if n.editable)

    def render(self, *, limit: int = 90, max_chars: int = 6000) -> str:
        if not self.nodes:
            return ""
        return render_nodes(self.nodes, self.screen_size, limit=limit, max_chars=max_chars)

    def ground(
        self,
        point: Sequence[float],
        *,
        radius: float = DEFAULT_GROUNDING_RADIUS,
    ) -> tuple[tuple[float, float], UiNode | None]:
        """把一个归一化点击点吸附到最近的可点控件中心。

        返回 ``(point, node)``：

        - 点已经落在某个可点控件内 → 原样返回该点，``node`` 是命中的控件；
        - 点在半径内偏离某个可点控件中心 → 返回该控件中心，``node`` 是它；
        - 半径内没有可点控件，或这帧没有节点 → 原样返回，``node`` 为 ``None``。
        """
        if len(point) != 2:
            return (float(point[0]), float(point[1])), None  # type: ignore[index]
        px, py = float(point[0]), float(point[1])
        if not self.nodes:
            return (px, py), None

        # 1) 已经点中某个可点控件：不动，但记下命中的是谁（trace 里能看懂点了什么）
        for node in self.actionable_nodes:
            if node.contains((px, py), self.screen_size):
                return (px, py), node

        # 2) 否则找半径内最近的可点控件中心
        best: UiNode | None = None
        best_distance = float("inf")
        for node in self.actionable_nodes:
            distance = node.distance_to((px, py), self.screen_size)
            if distance <= radius and distance < best_distance:
                best, best_distance = node, distance
        if best is None:
            return (px, py), None
        cx, cy = best.center(self.screen_size)
        return (float(cx), float(cy)), best


def build_observation(
    *,
    elements: Iterable[Mapping[str, Any]] | None = None,
    rows: Iterable[str] | None = None,
    xml_text: str | None = None,
    screen_size: tuple[int, int] = (0, 0),
    foreground: str | None = None,
    limit: int = 120,
) -> Observation:
    """从任意一种设备输出构造观测，按 ``elements → rows → xml`` 优先级取第一个可用的。"""
    from .nodes import nodes_signature

    nodes: list[UiNode] = []
    source = "none"

    if elements is not None:
        nodes = nodes_from_elements(elements, screen=screen_size, limit=limit)
        source = "elements"
    elif rows is not None:
        nodes = nodes_from_rows(rows, screen=screen_size)
        source = "rows"
    elif xml_text:
        nodes = nodes_from_xml(xml_text, screen=screen_size, limit=limit)
        source = "xml"

    return Observation(
        nodes=tuple(nodes),
        screen_size=screen_size,
        signature=nodes_signature(nodes) if nodes else "",
        source=source if nodes else "none",
        foreground=foreground,
    )


def text_signature(text: str) -> str:
    """没有结构信息时的签名兜底：界面文本 / 像素摘要。"""
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest() if text else ""
