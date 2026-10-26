"""UI 节点模型：把不同来源的界面结构统一成可推理、可校验的 ``UiNode``。

三种来源：

- ``elements``：设备层直接给出的结构化列表（PC 端 ``dump_hierarchy`` 解析结果、
  端内 ``AccessibilityNodeInfo`` 遍历结果）；
- ``xml``：uiautomator2 的 hierarchy XML（PC 端兜底）；
- ``rows``：端内 ``uiNodes()`` 的 9 段制表符行（向后兼容）。

设计约束（借鉴 nanoMuse 的 "画面优先、控件表辅助" 思路，独立实现）：

1. 节点信息只用来**读小字和瞄准**，不替代截图判断；
2. 渲染结果必须紧凑（节点数、字符数双上限），否则 prompt 会被界面噪声淹没；
3. 坐标一律归一化到 0-1000，与 ``Action`` 协议一致，避免设备分辨率耦合。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

SYSTEM_UI_PACKAGES = frozenset({"com.android.systemui"})

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_FLAG_SPLIT_RE = re.compile(r"[,\s|]+")

_TRUE = {"1", "true", "yes", "y"}

# 归一化坐标网格边长；与核心 Action 协议保持一致
GRID = 1000


@dataclass(frozen=True)
class UiNode:
    """屏幕上的一个可读控件。

    ``bounds`` 是设备像素 ``(left, top, right, bottom)``，
    ``center`` 每次按 ``screen_size`` 现算，避免把分辨率写进节点。
    """

    text: str = ""
    desc: str = ""
    resource: str = ""
    cls: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    clickable: bool = False
    scrollable: bool = False
    editable: bool = False
    focused: bool = False
    package: str = ""

    # ------------------------------------------------ 派生属性

    @property
    def width(self) -> int:
        return max(0, self.bounds[2] - self.bounds[0])

    @property
    def height(self) -> int:
        return max(0, self.bounds[3] - self.bounds[1])

    @property
    def label(self) -> str:
        """最像"用户看到的文字"的那个字段。"""
        return self.text or self.desc or self.resource or self.cls

    @property
    def actionable(self) -> bool:
        """值得让模型瞄准的节点：可点、可滚、可编辑。"""
        return self.clickable or self.scrollable or self.editable

    def center(self, screen: tuple[int, int]) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        width = screen[0] or 1
        height = screen[1] or 1
        return (
            round((x1 + x2) / 2 / width * GRID),
            round((y1 + y2) / 2 / height * GRID),
        )

    def contains(self, point: Sequence[float], screen: tuple[int, int]) -> bool:
        """归一化点是否落在节点矩形内。"""
        x1, y1, x2, y2 = self.bounds
        width = screen[0] or 1
        height = screen[1] or 1
        px = float(point[0]) / GRID * width
        py = float(point[1]) / GRID * height
        return x1 <= px <= x2 and y1 <= py <= y2

    def distance_to(self, point: Sequence[float], screen: tuple[int, int]) -> float:
        """归一化点到节点中心的距离（0-1000 网格上的欧氏距离）。"""
        cx, cy = self.center(screen)
        return ((float(point[0]) - cx) ** 2 + (float(point[1]) - cy) ** 2) ** 0.5

    def to_line(self, screen: tuple[int, int]) -> str:
        """渲染成一行紧凑文本，格式与既有 ``ui_context`` 保持兼容。"""
        cx, cy = self.center(screen)
        flags = []
        if self.clickable:
            flags.append("click")
        if self.scrollable:
            flags.append("scroll")
        if self.editable:
            flags.append("edit")
        if self.focused:
            flags.append("focus")
        resource = self.resource.rsplit("/", 1)[-1]
        klass = self.cls.rsplit(".", 1)[-1]
        x1, y1, x2, y2 = self.bounds
        return (
            f'- text="{self.text}" desc="{self.desc}" id="{resource}" '
            f'class="{klass}" center=[{cx},{cy}] bounds=[{x1},{y1},{x2},{y2}] '
            f'flags={",".join(flags) or "-"}'
        )

    def stable_key(self) -> str:
        """用于界面签名：只保留"用户能看到的差异"，忽略焦点等瞬时抖动。"""
        x1, y1, x2, y2 = self.bounds
        return f"{self.text}|{self.desc}|{self.resource}|{x1},{y1},{x2},{y2}"


# ---------------------------------------------------------------- 构造


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in _TRUE
    return default


def _as_bounds(value: Any) -> tuple[int, int, int, int]:
    """接受 (x1,y1,x2,y2) 序列或 uiautomator2 的 ``[x1,y1][x2,y2]`` 字符串。"""
    if isinstance(value, str):
        match = _BOUNDS_RE.search(value)
        if not match:
            return (0, 0, 0, 0)
        return tuple(int(g) for g in match.groups())  # type: ignore[return-value]
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return tuple(int(v) for v in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return (0, 0, 0, 0)
    return (0, 0, 0, 0)


def _clean_text(value: Any, limit: int = 80) -> str:
    """压平空白、把双引号换成单引号（避免破坏行格式），再截断。"""
    text = " ".join(str(value or "").split()).replace('"', "'")
    return text[:limit]


def _as_flags(value: Any) -> set[str]:
    if isinstance(value, (set, frozenset, list, tuple)):
        return {str(v).strip().lower() for v in value if str(v).strip()}
    if isinstance(value, str):
        return {p for p in _FLAG_SPLIT_RE.split(value.strip().lower()) if p and p != "-"}
    return set()


def node_from_element(element: Mapping[str, Any]) -> UiNode:
    """把设备层的一条结构记录转成 ``UiNode``。

    兼容三种写法：``bounds`` 像素四元组、``center`` 归一化中心（无 bounds 时退化为
    零尺寸矩形）、以及 ``flags`` 字符串 / 布尔字段混用。
    """
    flags = _as_flags(element.get("flags"))
    cls = str(element.get("class") or element.get("cls") or "")
    editable = _as_bool(element.get("editable")) or "edit" in flags or cls.endswith("EditText")
    bounds = _as_bounds(element.get("bounds"))
    if bounds == (0, 0, 0, 0):
        center = element.get("center")
        if isinstance(center, (list, tuple)) and len(center) == 2 and bounds == (0, 0, 0, 0):
            # 只有归一化中心时，构造一个 1×1 的退化矩形（仍可用于签名与去重）
            bounds = (int(center[0]), int(center[1]), int(center[0]) + 1, int(center[1]) + 1)
    return UiNode(
        text=_clean_text(element.get("text")),
        desc=_clean_text(element.get("desc") or element.get("content-desc")),
        resource=_clean_text(element.get("resource") or element.get("resource-id")),
        cls=_clean_text(cls),
        bounds=bounds,
        clickable=_as_bool(element.get("clickable")) or "click" in flags,
        scrollable=_as_bool(element.get("scrollable")) or "scroll" in flags,
        editable=editable,
        focused=_as_bool(element.get("focused")) or "focus" in flags,
        package=str(element.get("package") or "").strip(),
    )


def nodes_from_elements(
    elements: Iterable[Mapping[str, Any]],
    *,
    screen: tuple[int, int] = (0, 0),
    limit: int = 120,
    skip_system_ui: bool = True,
    skip_empty: bool = True,
) -> list[UiNode]:
    """结构记录 → 节点列表，按设备层顺序保留。"""
    nodes: list[UiNode] = []
    seen: set[str] = set()
    for element in elements:
        if not isinstance(element, Mapping):
            continue
        node = node_from_element(element)
        if skip_system_ui and node.package in SYSTEM_UI_PACKAGES:
            continue
        if node.width <= 0 or node.height <= 0:
            continue
        if skip_empty and not (node.text or node.desc or node.actionable):
            continue
        key = node.to_line(screen)
        if key in seen:
            continue
        seen.add(key)
        nodes.append(node)
        if len(nodes) >= limit:
            break
    return nodes


def nodes_from_rows(rows: Iterable[str], *, screen: tuple[int, int] = (0, 0)) -> list[UiNode]:
    """端内 ``uiNodes()`` 的 ``text\\tdesc\\tid\\tclass\\tleft\\ttop\\tright\\tbottom\\tflags`` 行。"""
    elements: list[dict[str, Any]] = []
    for row in rows:
        parts = str(row).split("\t")
        if len(parts) != 9:
            continue
        text, desc, resource, klass, left, top, right, bottom, flags = parts
        try:
            bounds = (int(left), int(top), int(right), int(bottom))
        except ValueError:
            continue
        elements.append({
            "text": text, "desc": desc, "resource": resource, "class": klass,
            "bounds": bounds, "flags": flags,
        })
    return nodes_from_elements(elements, screen=screen)


def nodes_from_xml(xml_text: str, *, screen: tuple[int, int] = (0, 0), limit: int = 120) -> list[UiNode]:
    """uiautomator2 hierarchy XML → 节点列表（PC 端兜底路径）。"""
    if not xml_text or not xml_text.strip():
        return []
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    elements: list[dict[str, Any]] = []
    for node in root.iter("node"):
        flags = []
        if node.get("clickable") == "true":
            flags.append("click")
        if node.get("scrollable") == "true":
            flags.append("scroll")
        if node.get("focused") == "true":
            flags.append("focus")
        klass = node.get("class") or ""
        elements.append({
            "text": node.get("text") or "",
            "desc": node.get("content-desc") or "",
            "resource": node.get("resource-id") or "",
            "class": klass,
            "bounds": node.get("bounds") or "",
            "flags": ",".join(flags),
            "editable": klass.endswith("EditText") or node.get("editable") == "true",
            "package": node.get("package") or "",
        })
        if len(elements) >= limit * 3:
            break
    return nodes_from_elements(elements, screen=screen, limit=limit)


# ---------------------------------------------------------------- 渲染 / 签名


def render_nodes(
    nodes: Sequence[UiNode],
    screen: tuple[int, int],
    *,
    limit: int = 90,
    max_chars: int = 6000,
) -> str:
    """节点列表 → 紧凑 prompt 文本（行数、字符数双上限）。"""
    lines: list[str] = []
    for node in nodes[:limit]:
        lines.append(node.to_line(screen))
    return "\n".join(lines)[:max_chars]


def nodes_signature(nodes: Sequence[UiNode]) -> str:
    """界面结构签名：只对"用户看得到的东西"取哈希，用于检测动作是否真的生效。"""
    payload = "\n".join(node.stable_key() for node in nodes)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest() if payload else ""
