"""Session:管理一次任务执行的历史、产物落盘、统计。"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ..core.action import Action, ActionOutput
from ..reasoning.base import StepRecord
from .task import Task


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

    def __init__(self, task: Task, base_dir: Path | str):
        self.task = task
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
        self._pending_interactions: list[dict[str, Any]] = []

    # ----------------------- 保存产物 -----------------------

    def save_screenshot(self, step: int, image: Image.Image, attempt: int = 0) -> Path:
        suffix = f"_retry_{attempt}" if attempt else ""
        path = self.dir / f"step_{step:03d}{suffix}.png"
        image.save(path, format="PNG")
        return path

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
    ) -> StepRecord:
        notes = list(notes or [])
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
        self._accumulate_usage(action_out.usage)
        self._append_trace(
            record, screenshot_path, action_out.usage,
            prompt_text=action_out.prompt_text,
            reasoning_time=reasoning_time,
            execution_time=execution_time,
        )
        return record

    # ----------------------- 状态 -----------------------

    def consecutive_failures(self) -> int:
        count = 0
        for rec in reversed(self.history):
            if rec.execution_success is False:
                count += 1
            else:
                break
        return count

    def consecutive_identical_actions(self) -> int:
        """末尾连续多少步动作完全相同(action.type + parameters)。"""
        if not self.history:
            return 0
        import json as _json
        last = self.history[-1]
        last_key = (last.action.type, _json.dumps(last.action.parameters, sort_keys=True))
        count = 0
        for rec in reversed(self.history):
            key = (rec.action.type, _json.dumps(rec.action.parameters, sort_keys=True))
            if key == last_key:
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
        )
        summary_obj: dict[str, Any] = asdict(result)
        summary_obj["elapsed_seconds"] = round(time.time() - self._start_ts, 2)
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

    def _append_trace(
        self,
        record: StepRecord,
        screenshot_path: Path | None,
        usage: dict[str, Any] | None,
        prompt_text: str = "",
        reasoning_time: float = 0.0,
        execution_time: float = 0.0,
    ) -> None:
        line: dict[str, Any] = {
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
            "interactions": self._pending_interactions[:],
        }
        try:
            with self.trace_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            self._pending_interactions.clear()
        except Exception as exc:
            logger.warning("append trace failed: %s", exc)
