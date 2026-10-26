"""进度账本：把每一步"做了什么、成没成、界面变没变"记成可读的一条流水。

它解决两个具体问题：

1. **重复动作识别要容差。** 模型点击一个没反应的复选框时，每次都会写一句新的
   reasoning、坐标再偏一两个像素；按字符串比对会认为"动作不同"，永远触发不了死循环
   保护。这里按动作类型 + 关键参数 + 坐标容差比较（借鉴 nanoMuse 的 ``_same_action``
   思路，独立实现）。
2. **失败要能进 prompt。** 只把结果写进 trace 是给人看的，模型下一步看不到；账本
   提供 ``render()``，把最近几步压成几行文本，可直接拼进下一轮指令。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# 坐标容差（0-1000 网格）：40 ≈ 1080 宽屏上的 43 像素，约一根手指的宽度
DEFAULT_POINT_TOLERANCE = 40.0

# 参与"是否同一个动作"比较的参数键（其余如 reasoning 措辞变化不算新动作）
_COMPARED_KEYS = ("text", "app_name", "seconds", "direction")
_POINT_KEYS = ("point", "start_point", "end_point")


def action_digest(
    action_type: str,
    parameters: Mapping[str, Any] | None = None,
) -> tuple[Any, ...]:
    """把动作压成可比较的元组（保留原始数值，仅用于展示/快照）。

    真正判断"是不是重复动作"请用 :func:`same_action`：分桶量化在容差边界上不稳定
    （500 与 503 在 40 的桶里可能分到两边），按距离比较才可靠。
    """
    params = dict(parameters or {})
    digest: list[Any] = [str(action_type)]
    for key in _COMPARED_KEYS:
        if key in params:
            digest.append((key, str(params[key])))
    for key in _POINT_KEYS:
        value = params.get(key)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            digest.append((key, (value[0], value[1])))
        elif value is not None:
            digest.append((key, str(value)))
    return tuple(digest)


def _is_point(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 2


def same_action(
    a_type: str,
    a_params: Mapping[str, Any] | None,
    b_type: str,
    b_params: Mapping[str, Any] | None,
    *,
    tolerance: float = DEFAULT_POINT_TOLERANCE,
) -> bool:
    """两个动作是否算"同一个动作"：类型相同、关键参数相同、坐标相距不超过容差。"""
    if str(a_type) != str(b_type):
        return False
    a = dict(a_params or {})
    b = dict(b_params or {})
    for key in _COMPARED_KEYS:
        if str(a.get(key)) != str(b.get(key)):
            return False
    for key in _POINT_KEYS:
        va, vb = a.get(key), b.get(key)
        if va is None and vb is None:
            continue
        if not (_is_point(va) and _is_point(vb)):
            return False
        try:
            if abs(float(va[0]) - float(vb[0])) > tolerance:
                return False
            if abs(float(va[1]) - float(vb[1])) > tolerance:
                return False
        except (TypeError, ValueError):
            if str(va) != str(vb):
                return False
    return True


@dataclass(frozen=True)
class StepEntry:
    """账本里的一步。"""

    step: int
    action: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    summary: str = ""
    outcome: str = "ok"  # ok | failed | rejected | skipped
    note: str = ""
    screen_signature: str = ""
    foreground: str | None = None

    def digest(self, *, tolerance: float = DEFAULT_POINT_TOLERANCE) -> tuple[Any, ...]:
        return action_digest(self.action, self.parameters)

    def matches(
        self,
        action_type: str,
        parameters: Mapping[str, Any] | None,
        *,
        tolerance: float = DEFAULT_POINT_TOLERANCE,
    ) -> bool:
        """本条记录与该动作是否算同一个动作（坐标按容差比较）。"""
        return same_action(
            self.action, self.parameters, action_type, parameters, tolerance=tolerance
        )

    def render(self) -> str:
        """一行给模型看的流水。"""
        head = f"Step {self.step}: {self.action}"
        if self.summary:
            head += f"（{self.summary}）"
        if self.outcome != "ok":
            head += f" → {self.outcome}"
        if self.note:
            head += f"；{self.note}"
        return head


@dataclass
class ProgressLedger:
    """一次任务内的步进流水。"""

    tolerance: float = DEFAULT_POINT_TOLERANCE
    entries: list[StepEntry] = field(default_factory=list)

    # ------------------------------------------------ 写入

    def record(self, entry: StepEntry) -> None:
        self.entries.append(entry)

    def reset(self) -> None:
        self.entries.clear()

    # ------------------------------------------------ 查询

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def last(self) -> StepEntry | None:
        return self.entries[-1] if self.entries else None

    @property
    def last_success_step(self) -> int | None:
        for entry in reversed(self.entries):
            if entry.outcome == "ok":
                return entry.step
        return None

    def consecutive_failures(self) -> int:
        count = 0
        for entry in reversed(self.entries):
            if entry.outcome in ("failed", "rejected"):
                count += 1
            else:
                break
        return count

    def repeated_streak(
        self,
        *,
        action_type: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> int:
        """末尾连续重复同一动作的步数。

        给出 ``action_type``/``parameters`` 时把"即将执行的这一步"也算进去，
        这样在执行前就能判断会不会构成重复。
        """
        if action_type is not None:
            streak = 1
            for entry in reversed(self.entries):
                if entry.matches(action_type, parameters, tolerance=self.tolerance):
                    streak += 1
                else:
                    break
            return streak
        if not self.entries:
            return 0
        last = self.entries[-1]
        streak = 0
        for entry in reversed(self.entries):
            if entry.matches(last.action, last.parameters, tolerance=self.tolerance):
                streak += 1
            else:
                break
        return streak

    def unchanged_streak(self) -> int:
        """末尾连续"界面没变"的步数。"""
        if not self.entries:
            return 0
        signature = self.entries[-1].screen_signature
        if not signature:
            return 0
        streak = 0
        for entry in reversed(self.entries):
            if entry.screen_signature == signature:
                streak += 1
            else:
                break
        return streak

    def render(self, limit: int = 8) -> str:
        """最近 ``limit`` 步压成文本；空账本返回空串。"""
        if not self.entries:
            return ""
        return "\n".join(entry.render() for entry in self.entries[-limit:])

    def snapshot(self) -> dict[str, Any]:
        """给 summary.json / 调试器用的结构化快照。"""
        return {
            "steps": len(self.entries),
            "last_success_step": self.last_success_step,
            "consecutive_failures": self.consecutive_failures(),
            "repeated_streak": self.repeated_streak(),
            "entries": [
                {
                    "step": e.step, "action": e.action, "outcome": e.outcome,
                    "note": e.note, "summary": e.summary,
                }
                for e in self.entries
            ],
        }
