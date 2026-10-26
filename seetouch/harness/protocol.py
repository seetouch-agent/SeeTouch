"""动作协议层：把模型输出的动作和当前界面观测对齐。

模型输出的是"意图"，设备需要的是"像素"。两者之间的缝隙靠这一层补：

- ``CLICK`` 的落点如果落在空白处、但离某个可点控件的中心很近，就把点吸附过去；
- 落点已经完全不在任何控件上时，不去猜，只记一条诊断，让策略层决定要不要换路子；
- 所有修正都留痕（``note``），trace 里能看出"模型点的是哪、真正点的是哪"。

吸附只在有条件时进行：没有结构信息的设备（纯视觉链路）保持原样，行为与升级前一致。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from ..core.action import ACTION_CLICK, ACTION_LONG_PRESS, ACTION_SCROLL, Action
from .nodes import UiNode
from .observation import DEFAULT_GROUNDING_RADIUS, Observation

# 需要瞄准的动作：点击与长按都作用于一个点，落点偏了同样会打空
POINT_ACTIONS = (ACTION_CLICK, ACTION_LONG_PRESS, ACTION_SCROLL)


@dataclass(frozen=True)
class GroundingResult:
    """一次落点校准的结果。"""

    action: Action
    node: UiNode | None = None
    moved: bool = False
    note: str = ""

    @property
    def label(self) -> str:
        return self.node.label if self.node else ""


def _format_point(point: Sequence[float]) -> str:
    return f"[{point[0]:.0f},{point[1]:.0f}]"


def ground_action(
    action: Action,
    observation: Observation | None,
    *,
    radius: float = DEFAULT_GROUNDING_RADIUS,
    enabled: bool = True,
) -> GroundingResult:
    """把点击类动作的落点对齐到当前界面的可点控件。"""
    if not enabled or observation is None or not observation.has_nodes:
        return GroundingResult(action=action)
    if action.type not in (ACTION_CLICK, ACTION_LONG_PRESS):
        return GroundingResult(action=action)

    point = action.parameters.get("point")
    if not (isinstance(point, (list, tuple)) and len(point) == 2):
        return GroundingResult(action=action)

    grounded, node = observation.ground(point, radius=radius)
    if node is None:
        return GroundingResult(
            action=action,
            note=f"click_off_target: {_format_point(point)} 附近没有可点控件",
        )

    moved = (round(float(point[0])) != round(grounded[0])
             or round(float(point[1])) != round(grounded[1]))
    if not moved:
        return GroundingResult(action=action, node=node, note="")

    grounded_action = replace(
        action,
        parameters={**action.parameters, "point": [int(round(grounded[0])), int(round(grounded[1]))]},
    )
    return GroundingResult(
        action=grounded_action,
        node=node,
        moved=True,
        note=(
            f"click_grounded: {_format_point(point)} -> {_format_point(grounded)}"
            f" 命中「{node.label}」"
        ),
    )


def validate_action(action: Action, observation: Observation | None = None) -> list[str]:
    """返回动作的诊断信息（不抛异常、不修改动作）。

    这些诊断进 trace，用于事后统计"模型点的位置有多离谱"，而不是用来打断任务。
    """
    problems: list[str] = []
    point = action.parameters.get("point")
    if action.type in (ACTION_CLICK, ACTION_LONG_PRESS):
        prefix = "click" if action.type == ACTION_CLICK else "long_press"
        if not (isinstance(point, (list, tuple)) and len(point) == 2):
            return [f"{prefix}_without_point"]
        x, y = float(point[0]), float(point[1])
        if not (0 <= x <= 1000 and 0 <= y <= 1000):
            problems.append("point_out_of_range")
        if observation is not None and observation.has_nodes:
            if not any(n.contains((x, y), observation.screen_size) for n in observation.actionable_nodes):
                problems.append(f"{prefix}_on_empty_area")
    elif action.type == ACTION_SCROLL:
        for key in ("start_point", "end_point"):
            value = action.parameters.get(key)
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                problems.append(f"{key}_missing")
    return problems
