"""循环策略：把"继续 / 提醒 / 升级 / 终止"的判断从主循环里抽出来。

以前这些判断散在 ``_step_once`` 的末尾：连续失败数、连续相同动作数、步数上限各写一段
``if``，而且只有终止、没有中间档。结果是模型在"界面不动"时只会收到一句固定的提示，
到了阈值就直接被杀掉，中间没有过渡。

策略对象把它变成一条显式的阶梯：

- ``nudge``：温和提醒，拼进下一轮指令；
- ``escalate``：换策略的指令（BACK / 回桌面 / 问用户），仍继续执行；
- ``abort``：带终止原因的收尾。

阈值全部可配，默认值对齐原先的行为，避免升级本身改变已有任务的结局。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoopHint:
    """一次策略判定结果。"""

    code: str
    level: str  # info | warn | critical
    text: str = ""
    action: str = "nudge"  # nudge | escalate | abort
    terminal_reason: str | None = None


# 缺省文案与升级前的 prompt 保持一致措辞，避免模型行为突然变化
UNCHANGED_NUDGE = (
    "注意：当前界面与之前 {streak} 步相同，上一步动作很可能没有生效。"
    "不要重复相同操作；改用其他控件、滚动、返回或等待。"
)
UNCHANGED_ESCALATE = (
    "注意：界面已经连续 {streak} 步没有任何变化，当前思路大概率走不通。"
    "请换一条路径：BACK 返回上一层、回桌面重新 OPEN 目标应用、"
    "或 ASK_USER 说明卡在哪里。不要再用同样的坐标或同样的动作。"
)
REPEAT_NUDGE = (
    "注意：同样的动作已经连续执行 {streak} 次，界面没有推进。"
    "下一步必须换动作类型或换目标控件。"
)
IDLE_ABORT = (
    "连续 {streak} 步界面没有任何变化，任务已停止（idle_exhausted）。"
)
BUDGET_ABORT = "运行预算耗尽（{reason}），任务已停止。"


class LoopPolicy:
    """按账本统计决定下一步该怎么提示或收尾。"""

    def __init__(
        self,
        *,
        max_idle_steps: int = 8,
        unchanged_nudge_at: int = 2,
        unchanged_escalate_at: int = 4,
        repeat_nudge_at: int = 2,
        repeat_abort_at: int | None = None,
    ) -> None:
        if max_idle_steps < 1:
            raise ValueError("max_idle_steps must be >= 1")
        if unchanged_nudge_at < 1 or unchanged_escalate_at < 1:
            raise ValueError("unchanged thresholds must be >= 1")
        if unchanged_escalate_at < unchanged_nudge_at:
            raise ValueError("unchanged_escalate_at must be >= unchanged_nudge_at")
        if repeat_nudge_at < 1:
            raise ValueError("repeat_nudge_at must be >= 1")
        self.max_idle_steps = max_idle_steps
        self.unchanged_nudge_at = unchanged_nudge_at
        self.unchanged_escalate_at = unchanged_escalate_at
        self.repeat_nudge_at = repeat_nudge_at
        self.repeat_abort_at = repeat_abort_at

    def evaluate(
        self,
        *,
        step: int,
        unchanged_streak: int = 0,
        repeated_streak: int = 0,
        budget_reason: str | None = None,
    ) -> LoopHint | None:
        """返回当前该给出的提示；没有可提示的返回 ``None``。

        判定顺序即优先级：预算 > 空转终止 > 重复终止 > 换策略 > 温和提醒。
        """
        if budget_reason:
            return LoopHint(
                code=budget_reason,
                level="critical",
                text=BUDGET_ABORT.format(reason=budget_reason),
                action="abort",
                terminal_reason=budget_reason,
            )

        if unchanged_streak >= self.max_idle_steps:
            return LoopHint(
                code="idle_exhausted",
                level="critical",
                text=IDLE_ABORT.format(streak=unchanged_streak),
                action="abort",
                terminal_reason="idle_exhausted",
            )

        if self.repeat_abort_at is not None and repeated_streak >= self.repeat_abort_at:
            return LoopHint(
                code="stuck_loop",
                level="critical",
                text=REPEAT_NUDGE.format(streak=repeated_streak),
                action="abort",
                terminal_reason="stuck_loop",
            )

        if unchanged_streak >= self.unchanged_escalate_at:
            return LoopHint(
                code="unchanged_escalate",
                level="critical",
                text=UNCHANGED_ESCALATE.format(streak=unchanged_streak),
                action="escalate",
            )

        if repeated_streak >= self.repeat_nudge_at:
            return LoopHint(
                code="repeat_nudge",
                level="warn",
                text=REPEAT_NUDGE.format(streak=repeated_streak),
                action="nudge",
            )

        if unchanged_streak >= self.unchanged_nudge_at:
            return LoopHint(
                code="unchanged_nudge",
                level="warn",
                text=UNCHANGED_NUDGE.format(streak=unchanged_streak),
                action="nudge",
            )

        return None
