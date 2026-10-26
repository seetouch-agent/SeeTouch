"""SeeTouch harness：主循环之外的一层"运行支撑"。

拆成四件事，各自可测：

- :mod:`~seetouch.harness.nodes`       界面节点模型（多来源归一化 + 紧凑渲染）
- :mod:`~seetouch.harness.observation` 一帧观测（结构签名 + 点击落点校准）
- :mod:`~seetouch.harness.ledger`      进度账本（容差去重 + 可渲染流水）
- :mod:`~seetouch.harness.budget`      运行预算（步数 / 时间 / token）
- :mod:`~seetouch.harness.policy`      循环策略（提醒 / 升级 / 终止阶梯）
- :mod:`~seetouch.harness.protocol`    动作与观测的对齐（落点吸附 + 诊断）

设计参考了 nanoMuse（GPL-3.0-or-later）公开的 harness 文档与手机 operator 的实现
思路（画面优先、节点表辅助、动作容差去重、空转步预算、失败回灌 prompt）。SeeTouch 是
Apache-2.0，这里只重写设计、没有复制其源码，具体实现与接口均为独立编写。
"""

from __future__ import annotations

from .budget import RunBudget
from .context import (
    ContextBudget,
    PinnedInputs,
    compact_history,
    estimate_tokens,
)
from .ledger import (
    DEFAULT_POINT_TOLERANCE,
    ProgressLedger,
    StepEntry,
    action_digest,
    same_action,
)
from .nodes import (
    GRID,
    UiNode,
    node_from_element,
    nodes_from_elements,
    nodes_from_rows,
    nodes_from_xml,
    nodes_signature,
    render_nodes,
)
from .observation import (
    DEFAULT_GROUNDING_RADIUS,
    Observation,
    build_observation,
    text_signature,
)
from .policy import LoopHint, LoopPolicy
from .protocol import GroundingResult, ground_action, validate_action

__all__ = [
    "DEFAULT_GROUNDING_RADIUS",
    "DEFAULT_POINT_TOLERANCE",
    "GRID",
    "GroundingResult",
    "LoopHint",
    "LoopPolicy",
    "ContextBudget",
    "Observation",
    "PinnedInputs",
    "compact_history",
    "estimate_tokens",
    "ProgressLedger",
    "RunBudget",
    "StepEntry",
    "UiNode",
    "action_digest",
    "build_observation",
    "ground_action",
    "node_from_element",
    "nodes_from_elements",
    "nodes_from_rows",
    "nodes_from_xml",
    "nodes_signature",
    "render_nodes",
    "same_action",
    "text_signature",
    "validate_action",
]
