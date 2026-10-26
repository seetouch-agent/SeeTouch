"""Session:管理一次任务执行的历史、产物落盘、统计。"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from ..core.action import Action, ActionOutput
from ..harness.ledger import same_action
from ..reasoning.base import StepRecord
from .task import Task
from .outcome import failure_code


logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Runner 单步执行的完整可观测数据包。

    CLI 和调试器都通过此数据类获取每步结果。
    """

    step: int
    screenshot: Image.Image
    screenshot_path: Path | None
    prompt_text: str
    raw_output: str
    reasoning_content: str
    action: Action
    screen_summary: str
    action_summary: str
    execution_success: bool | None
    notes: list[str]
    usage: dict[str, Any] | None
    reasoning_time: float
    execution_time: float
    terminal: bool
    terminal_reason: str | None = None


@dataclass
class RunResult:
    task_id: str
    instruction: str
    total_steps: int
    completed: bool
    aborted_reason: str | None = None
    runs_dir: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    elapsed_seconds: float = 0.0
    reason_code: str | None = None
    answer: str = ""
    answer_source_step: int | None = None
    answer_screenshot: str | None = None
    used_memory_ids: list[str] = field(default_factory=list)
    learned_memory_id: str | None = None
    learning_status: str = "disabled"
    memory_suggestions: list[dict] = field(default_factory=list)
    reasoner: str | None = None
    model_id: str | None = None
    terminal_reason: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    total_tokens: int = 0
    total_cached_tokens: int = 0


class Session:
    """一次任务执行的上下文。

    目录布局:
        <runs_dir>/<task_id>/
            step_001.png
            step_002.png
            ...
            trace.jsonl        # 每行一个 step record(JSON)
            summary.json       # 任务总结(任务完成或终止时写入)
    """

    def __init__(self, task: Task, base_dir: Path | str, metadata: dict[str, Any] | None = None):
        self.task = task
        self.metadata = dict(metadata or {})
        self.dir = Path(base_dir) / task.task_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.dir / "trace.jsonl"
        self.summary_path = self.dir / "summary.json"
        self.history: list[StepRecord] = []
        self._completed: bool = False
        self._aborted_reason: str | None = None
        self._start_ts: float = time.time()
        self._tokens_in: int = 0
        self._tokens_out: int = 0
        self._cached_tokens: int = 0
        self._pending_interactions: list[dict[str, Any]] = []
        self._screenshots: dict[int, Path] = {}
        self._answer = ""
        self._answer_source_step: int | None = None
        self._answer_screenshot: str | None = None
        self.used_memory_ids: list[str] = []
        self.learned_memory_id: str | None = None
        self.learning_status = "disabled"
        self.memory_suggestions: list[dict] = []

    # ----------------------- 保存产物 -----------------------

    def save_screenshot(self, step: int, image: Image.Image, attempt: int = 0) -> Path:
        suffix = f"_retry_{attempt}" if attempt else ""
        path = self.dir / f"step_{step:03d}{suffix}.png"
        image.save(path, format="PNG")
        self._screenshots[step] = path
        return path

    def set_answer(self, parameters: dict[str, Any], current_step: int) -> None:
        self._answer = parameters.get("answer", parameters.get("text", "")) or ""
        if not self._answer:
            return
        source = parameters.get("source_step", current_step)
        # Never invent an evidence image for a missing/future source step.
        if source not in self._screenshots:
            self.record_interaction({"type": "invalid_answer_source", "step": current_step, "requested_step": source})
            return
        self._answer_source_step = source
        path = self._screenshots.get(source)
        self._answer_screenshot = str(path) if path else None

    def record_interaction(self, event: dict[str, Any]) -> None:
        """Questions/control boundaries only; never records a human's device operations."""
        record = {"timestamp": time.time(), **event}
        self._pending_interactions.append(record)
        with (self.dir / "interactions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_step(
        self,
        step: int,
        action_out: ActionOutput,
        execution_success: bool | None,
        notes: list[str] | None = None,
        screenshot_path: Path | None = None,
        reasoning_time: float = 0.0,
        execution_time: float = 0.0,
        usage_already_counted: bool = False,
        ui_context: str = "",
        screen_unchanged_streak: int = 1,
    ) -> StepRecord:
        notes = list(notes or [])
        if action_out.parse_error:
            snippet = " ".join((action_out.raw_output or "").split())[:160]
            notes.append(
                "上一次输出不是合法动作 JSON："
                f"{snippet}；下一步只输出一个 JSON 对象，不要解释。"
            )
        if not self.history and self.used_memory_ids:
            notes.append("本次匹配记忆：" + ", ".join(self.used_memory_ids))
        record = StepRecord(
            step=step,
            action=action_out.action,
            screen_summary=action_out.screen_summary,
            action_summary=action_out.action_summary,
            execution_success=execution_success,
            raw_output=action_out.raw_output,
            notes=notes,
        )
        self.history.append(record)
        if not usage_already_counted:
            self._accumulate_usage(action_out.usage)
        self._append_trace(
            record, screenshot_path, action_out.usage,
            prompt_text=action_out.prompt_text,
            reasoning_time=reasoning_time,
            execution_time=execution_time,
            ui_context=ui_context,
            screen_unchanged_streak=screen_unchanged_streak,
        )
        return record

    # ----------------------- 状态 -----------------------

    def account_prediction(self, usage: dict[str, Any] | None) -> None:
        """Count received predictions, including those held/discarded after a pause."""
        self._accumulate_usage(usage)

    def consecutive_failures(self) -> int:
        count = 0
        for rec in reversed(self.history):
            if rec.execution_success is False:
                count += 1
            else:
                break
        return count

    def consecutive_identical_actions(self) -> int:
        """末尾连续多少步动作相同（坐标按手指宽度容差比较）。

        原实现把坐标向下取整到 20 的桶里再比字符串，跨桶边界时会漏判
        （例如 299 与 301 只差 2，却落进 280 和 300 两个桶）。这里改用
        :func:`seetouch.harness.ledger.same_action` 的距离比较，与账本共用一套判定。
        """
        if not self.history:
            return 0
        last = self.history[-1].action
        count = 0
        for rec in reversed(self.history):
            if same_action(last.type, last.parameters, rec.action.type, rec.action.parameters):
                count += 1
            else:
                break
        return count

    def mark_completed(self) -> None:
        self._completed = True

    def mark_aborted(self, reason: str) -> None:
        self._aborted_reason = reason

    @property
    def is_finished(self) -> bool:
        return self._completed or self._aborted_reason is not None

    @property
    def terminal_reason(self) -> str | None:
        if self._completed:
            return "completed"
        return self._aborted_reason

    def summarize(self) -> RunResult:
        result = RunResult(
            task_id=self.task.task_id,
            instruction=self.task.instruction,
            total_steps=len(self.history),
            completed=self._completed,
            aborted_reason=self._aborted_reason,
            runs_dir=str(self.dir),
            total_input_tokens=self._tokens_in,
            total_output_tokens=self._tokens_out,
            elapsed_seconds=round(time.time() - self._start_ts, 2),
            reason_code=failure_code(self._aborted_reason),
            answer=self._answer, answer_source_step=self._answer_source_step,
            answer_screenshot=self._answer_screenshot,
            used_memory_ids=self.used_memory_ids, learned_memory_id=self.learned_memory_id,
            learning_status=self.learning_status, memory_suggestions=self.memory_suggestions,
            reasoner=self.metadata.get("reasoner"),
            model_id=self.metadata.get("model_id"),
            terminal_reason=self.terminal_reason,
            started_at=self._start_ts,
            finished_at=time.time(),
            total_tokens=self._tokens_in + self._tokens_out,
            total_cached_tokens=self._cached_tokens,
        )
        summary_obj: dict[str, Any] = asdict(result)
        try:
            self.summary_path.write_text(
                json.dumps(summary_obj, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("save summary failed: %s", exc)
        return result

    # ----------------------- 内部 -----------------------

    def _accumulate_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        self._tokens_in += int(usage.get("input_tokens") or 0)
        self._tokens_out += int(usage.get("output_tokens") or 0)
        self._cached_tokens += int(usage.get("cached_tokens") or 0)

    def _append_trace(
        self,
        record: StepRecord,
        screenshot_path: Path | None,
        usage: dict[str, Any] | None,
        prompt_text: str = "",
        reasoning_time: float = 0.0,
        execution_time: float = 0.0,
        ui_context: str = "",
        screen_unchanged_streak: int = 1,
    ) -> None:
        line: dict[str, Any] = {
            "task_id": self.task.task_id,
            "model_id": self.metadata.get("model_id"),
            "reasoner": self.metadata.get("reasoner"),
            "step": record.step,
            "action_type": record.action.type,
            "parameters": record.action.parameters,
            "screen_summary": record.screen_summary,
            "action_summary": record.action_summary,
            "execution_success": record.execution_success,
            "notes": record.notes,
            "screenshot": str(screenshot_path) if screenshot_path else None,
            "usage": usage,
            "prompt_text": prompt_text,
            "reasoning_time": reasoning_time,
            "execution_time": execution_time,
            "ui_context": ui_context,
            "screen_unchanged_streak": screen_unchanged_streak,
            "interactions": self._pending_interactions[:],
        }
        try:
            with self.trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            self._pending_interactions.clear()
        except Exception as exc:
            logger.warning("append trace failed: %s", exc)
