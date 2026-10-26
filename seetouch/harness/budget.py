"""运行预算：步数、墙钟时间、token 三个维度统一记账。

以前这三条线分散在主循环、CLI 参数和 session 里：``max_steps`` 在 Task 上，
``task_timeout_seconds`` 在 Runner 上，token 只统计不设限。预算对象把它们收在一处，
终止原因也统一成 ``budget_*`` 前缀，方便评测脚本按原因归类。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunBudget:
    """一次任务的预算。``None`` 表示该维度不设限。"""

    max_steps: int | None = None
    max_seconds: float | None = None
    max_tokens: int | None = None
    started_at: float | None = None
    spent_tokens: int = 0
    _clock: Any = field(default=time.monotonic, repr=False, compare=False)

    # ------------------------------------------------ 生命周期

    def start(self, now: float | None = None) -> None:
        self.started_at = self._clock() if now is None else now
        self.spent_tokens = 0

    def reset(self) -> None:
        self.started_at = None
        self.spent_tokens = 0

    # ------------------------------------------------ 记账

    def consume_tokens(self, count: int | None) -> None:
        if isinstance(count, int) and count > 0:
            self.spent_tokens += count

    def elapsed(self, now: float | None = None) -> float:
        if self.started_at is None:
            return 0.0
        current = self._clock() if now is None else now
        return max(0.0, float(current) - float(self.started_at))

    def remaining_steps(self, step: int) -> int | None:
        if self.max_steps is None:
            return None
        return max(0, int(self.max_steps) - int(step))

    def remaining_seconds(self, now: float | None = None) -> float | None:
        if self.max_seconds is None:
            return None
        return max(0.0, float(self.max_seconds) - self.elapsed(now))

    def remaining_tokens(self) -> int | None:
        if self.max_tokens is None:
            return None
        return max(0, int(self.max_tokens) - self.spent_tokens)

    # ------------------------------------------------ 判定

    def exhausted(self, step: int, now: float | None = None) -> str | None:
        """返回第一个被耗尽的维度名，全部有余量时返回 ``None``。"""
        if self.max_steps is not None and int(step) > int(self.max_steps):
            return "max_steps"
        if self.max_seconds is not None and self.elapsed(now) >= float(self.max_seconds):
            return "task_timeout"
        if self.max_tokens is not None and self.spent_tokens >= int(self.max_tokens):
            return "token_budget"
        return None

    def snapshot(self, step: int, now: float | None = None) -> dict[str, Any]:
        return {
            "step": int(step),
            "elapsed_seconds": round(self.elapsed(now), 3),
            "spent_tokens": self.spent_tokens,
            "remaining_steps": self.remaining_steps(step),
            "remaining_seconds": (
                None if self.remaining_seconds(now) is None
                else round(self.remaining_seconds(now), 3)  # type: ignore[arg-type]
            ),
            "remaining_tokens": self.remaining_tokens(),
        }
