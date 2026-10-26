"""上下文预算与历史压缩。

升级前历史只保留最近 8 步（``history_window=8``）：长任务会丢掉早期决策，短任务又
浪费窗口。这里改成"按 token 预算压缩"：

- 估算整段 prompt 的 token（中文按 1 字≈1 token，拉丁按 4 字符≈1 token）；
- 超过预算比例时，把**较老的步骤**压成确定性摘要（不调模型，可复现）；
- 最近的步骤原样保留，保证模型看得到刚才发生了什么；
- 用户明确给出的补充（``PinnedInputs``）**永不参与压缩**，始终排在历史之前。

设计参考 Codex / Hermes 一类 agent 的上下文管理：预算驱动、压缩确定、用户输入保真。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

DEFAULT_CONTEXT_TOKENS = 64_000
DEFAULT_RESERVE_OUTPUT = 2_048
DEFAULT_COMPRESS_AT = 0.6
DEFAULT_KEEP_RECENT = 12
MIN_KEEP_RECENT = 4

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def estimate_tokens(text: str) -> int:
    """保守估算 token 数：CJK 每字 1 个，其余每 4 字符 1 个。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    rest = max(0, len(text) - cjk)
    return cjk + (rest + 3) // 4


@dataclass(frozen=True)
class ContextBudget:
    """一次对话的上下文预算（单位：token）。"""

    max_tokens: int = DEFAULT_CONTEXT_TOKENS
    reserve_output_tokens: int = DEFAULT_RESERVE_OUTPUT
    compress_at: float = DEFAULT_COMPRESS_AT
    keep_recent_steps: int = DEFAULT_KEEP_RECENT
    min_recent_steps: int = MIN_KEEP_RECENT

    def __post_init__(self) -> None:
        if self.max_tokens < 1024:
            raise ValueError("max_tokens must be >= 1024")
        if not 0 < self.compress_at <= 1:
            raise ValueError("compress_at must be in (0, 1]")
        if self.keep_recent_steps < self.min_recent_steps:
            raise ValueError("keep_recent_steps must be >= min_recent_steps")

    @property
    def prompt_budget(self) -> int:
        """留给 prompt 的预算（扣掉输出预留）。"""
        return max(1024, int(self.max_tokens) - int(self.reserve_output_tokens))

    @property
    def trigger_tokens(self) -> int:
        return int(self.prompt_budget * self.compress_at)

    def should_compress(self, used_tokens: int) -> bool:
        return used_tokens > self.trigger_tokens


@dataclass(frozen=True)
class CompactionResult:
    """压缩结果：给 prompt 的文本 + 可写进 trace 的统计。"""

    text: str
    kept_steps: int = 0
    digested_steps: int = 0
    estimated_tokens: int = 0
    compressed: bool = False
    dropped_steps: int = 0

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "kept_steps": self.kept_steps,
            "digested_steps": self.digested_steps,
            "dropped_steps": self.dropped_steps,
            "estimated_tokens": self.estimated_tokens,
            "compressed": self.compressed,
        }


@dataclass
class PinnedInputs:
    """用户明确给出的补充（ASK_USER 的回答、手动接管后说明等）。

    这些内容永不压缩：它们是用户意图的直接表达，丢了模型就会做出违背用户的操作。
    相同内容只保留一次，顺序按第一次出现。
    """

    entries: list[str] = field(default_factory=list)

    def add(self, text: str) -> bool:
        text = (text or "").strip()
        if not text or text in self.entries:
            return False
        self.entries.append(text)
        return True

    def extend(self, texts: Sequence[str]) -> None:
        for text in texts:
            self.add(text)

    def clear(self) -> None:
        self.entries.clear()

    def __len__(self) -> int:
        return len(self.entries)

    def render(self) -> str:
        if not self.entries:
            return ""
        body = "\n".join(f"- {e}" for e in self.entries)
        return f"用户明确要求（必须遵守，优先于历史推断）：\n{body}"


def _render_step(record: Any) -> str:
    """单步渲染，尽量与 prompts.build_history_summary 保持一致。"""
    lines = [f"Step {record.step}:"]
    if getattr(record, "screen_summary", ""):
        lines.append(f"- 界面描述: {record.screen_summary}")
    if getattr(record, "action_summary", ""):
        lines.append(f"- 操作描述: {record.action_summary}")
    action = getattr(record, "action", None)
    if action is not None:
        params = getattr(action, "parameters", {}) or {}
        lines.append(f"- 实际动作: {getattr(action, 'type', '')} {params}")
    success = getattr(record, "execution_success", None)
    if success is False:
        lines.append("- 执行状态: 失败")
    elif success is True:
        lines.append("- 执行状态: 成功")
    for note in getattr(record, "notes", []) or []:
        lines.append(f"- 备注: {note}")
    return "\n".join(lines)


def _digest_older(records: Sequence[Any], limit_notes: int = 6) -> str:
    """把较早的步骤压成确定性摘要（不调用模型，同样输入永远同样输出）。"""
    if not records:
        return ""
    counts: dict[str, int] = {}
    screens: list[str] = []
    failures: list[str] = []
    for record in records:
        kind = str(getattr(getattr(record, "action", None), "type", "") or "UNKNOWN")
        counts[kind] = counts.get(kind, 0) + 1
        screen = (getattr(record, "screen_summary", "") or "").strip()
        if screen and screen not in screens:
            screens.append(screen)
        if getattr(record, "execution_success", None) is False:
            note = "；".join(getattr(record, "notes", []) or [])[:120]
            failures.append(f"Step {getattr(record, 'step', '?')}: {note or '执行失败'}")

    parts = [f"早期步骤摘要（已压缩 {len(records)} 步）："]
    parts.append("- 动作分布：" + "，".join(f"{k}×{v}" for k, v in sorted(counts.items())))
    if screens:
        shown = "；".join(s[:40] for s in screens[:4])
        parts.append(f"- 到过的界面：{shown}")
    if failures:
        parts.append("- 失败记录：" + "；".join(failures[:limit_notes]))
    return "\n".join(parts)


def compact_history(
    history: Sequence[Any],
    *,
    budget: ContextBudget | None = None,
    fixed_tokens: int = 0,
    pinned_text: str = "",
) -> CompactionResult:
    """在预算内渲染历史：最近的步骤原样，较早的步骤压成摘要。

    ``fixed_tokens`` 是本次请求里除历史之外已经占用的 token（静态前缀、任务、观测、
    用户补充），用来决定历史还能用多少预算。
    """
    budget = budget or ContextBudget()
    available = budget.prompt_budget - fixed_tokens - estimate_tokens(pinned_text)
    if available <= 0:
        return CompactionResult(text="无", compressed=True, dropped_steps=len(history))

    records = list(history)
    if not records:
        return CompactionResult(text="无", estimated_tokens=0)

    # 0) 预算够就整段保留：这才是"不再固定只看 8 步"的意思
    full_text = "\n".join(_render_step(r) for r in records)
    if estimate_tokens(full_text) <= available:
        return CompactionResult(
            text=full_text,
            kept_steps=len(records),
            digested_steps=0,
            estimated_tokens=estimate_tokens(full_text),
            compressed=False,
        )

    # 1) 放不下时，先按 keep_recent 原样保留最近的步骤，其余压成摘要
    keep = min(len(records), budget.keep_recent_steps)
    while True:
        recent = records[-keep:] if keep else []
        older = records[: len(records) - keep]
        parts: list[str] = []
        if older:
            parts.append(_digest_older(older))
        parts.extend(_render_step(r) for r in recent)
        text = "\n".join(p for p in parts if p).strip() or "无"
        used = estimate_tokens(text)
        if used <= available or keep <= budget.min_recent_steps:
            break
        keep = max(budget.min_recent_steps, keep // 2)

    # 2) 仍然超预算：把摘要本身截断（保留最近步骤的完整信息）
    if used > available and text:
        text = text[: max(0, available * 2)]  # 粗截断后重新估算
        used = estimate_tokens(text)

    return CompactionResult(
        text=text,
        kept_steps=len(recent),
        digested_steps=len(older),
        dropped_steps=0,
        estimated_tokens=used,
        compressed=bool(older),
    )


def bind_budget(
    *,
    max_tokens: int | None = None,
    keep_recent: int | None = None,
    compress_at: float | None = None,
) -> ContextBudget:
    """从配置构造预算，非法值回退默认。"""
    kwargs: dict[str, Any] = {}
    if max_tokens and max_tokens >= 1024:
        kwargs["max_tokens"] = int(max_tokens)
    if keep_recent and keep_recent >= MIN_KEEP_RECENT:
        kwargs["keep_recent_steps"] = int(keep_recent)
    if compress_at and 0 < compress_at <= 1:
        kwargs["compress_at"] = float(compress_at)
    return ContextBudget(**kwargs)
