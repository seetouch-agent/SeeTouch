"""主循环 Runner:把 device / reasoner / guard / session 串成闭环。

支持两种消费方式:
  - run(task):连续执行直到任务结束(CLI 用)
  - start(task) + 循环调 step():逐步执行(调试器用)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from collections.abc import Callable
from .control import ExecutionControl, ReobserveRequired, RunStopped
from .outcome import api_failure_code

from .event_bus import (
    EventBus,
    STEP_EXECUTING,
    STEP_REASONING_DONE,
    STEP_REASONING_STARTED,
    STEP_SCREENSHOT_TAKEN,
)
from ..core.action import (
    ACTION_CLICK,
    ACTION_COMPLETE,
    ACTION_OPEN,
    ACTION_BACK,
    ACTION_SCROLL,
    ACTION_TYPE,
    ACTION_WAIT,
    ACTION_ASK_USER,
    ACTION_TAKE_OVER,
    ACTION_ANSWER,
    Action,
)
from ..device.base import (
    DeviceController,
    DeviceError,
    OpenAppNeedsVisual,
    OpenAppNotFound,
)
from ..perception.screen import downscale
from ..reasoning.base import Reasoner
from ..safety.guard import Guard
from .session import RunResult, Session, StepResult
from .task import Task
from .exceptions import VLMAPIError


logger = logging.getLogger(__name__)


class Runner:
    """单任务执行器。

    单步流程:
        1. 截屏 + 落盘
        2. Reasoner 预测 -> ActionOutput
        3. Guard 检查是否敏感动作,需要的话向用户确认
        4. 执行动作(COMPLETE 直接结束)
        5. 记录到 Session
        6. 检查终止条件:任务完成 / 用户拒绝 / 连续失败 / 步数耗尽

    支持两种使用模式:
        - run(task):自动消费全部步骤,返回 RunResult
        - start(task) + 循环 step():逐步执行,每步返回 StepResult
    """

    def __init__(
        self,
        device: DeviceController,
        reasoner: Reasoner,
        guard: Guard | None = None,
        runs_dir: Path | str = "runs",
        max_consecutive_failures: int = 2,
        max_consecutive_identical_actions: int = 3,
        max_open_misses: int = 3,
        event_bus: EventBus | None = None,
        action_settle_seconds: float = 1.0,
        control: ExecutionControl | None = None,
        interaction: Callable[[dict], dict] | None = None,
    ):
        self.device = device
        self.reasoner = reasoner
        self.guard = guard or Guard()
        self.runs_dir = Path(runs_dir)
        self.max_consecutive_failures = max_consecutive_failures
        self.max_consecutive_identical_actions = max_consecutive_identical_actions
        self.max_open_misses = max_open_misses
        self._event_bus = event_bus
        self.action_settle_seconds = action_settle_seconds
        self.control = control
        self.interaction = interaction
        self._interaction_context: list[str] = []

        # 运行状态(start() 初始化,step() 推进)
        self._session: Session | None = None
        self._task: Task | None = None
        self._current_step: int = 0
        self._finished: bool = True
        self._pending_visual_request: str | None = None
        self._visual_baseline_app: str | None = None
        self._open_miss_count = 0

    # ======================== 公开 API ========================

    def start(self, task: Task) -> None:
        """初始化一次任务执行。后续通过 step() 逐步推进。"""
        self._task = task
        self._session = Session(task, base_dir=self.runs_dir)
        self._interaction_context = []
        if self.control:
            self.control.event_sink = self._record_control_event
        self._current_step = 0
        self._finished = False
        self._pending_visual_request = None
        self._visual_baseline_app = None
        self._open_miss_count = 0
        logger.info(
            "start task: id=%s instruction=%r runs_dir=%s",
            task.task_id, task.instruction, self._session.dir,
        )

    def step(self) -> StepResult:
        """执行单步:截图 → 推理 → 执行 → 记录 → 返回结果。

        调用方根据 StepResult.terminal 判断任务是否结束。
        必须先调用 start() 再调用 step()。

        Raises:
            RuntimeError: 未调用 start() 或任务已结束时调用
        """
        if self._session is None or self._task is None:
            raise RuntimeError("must call start() before step()")
        if self._finished:
            raise RuntimeError("task already finished, call start() to begin a new task")

        self._current_step += 1
        step = self._current_step
        attempt = 0
        while True:
            try:
                revision = self._checkpoint()
                self._check_takeover()
                return self._step_once(step, revision, attempt)
            except ReobserveRequired:
                attempt += 1
            except RunStopped:
                return self._stopped_result(step)
            except InteractionUnavailable:
                return self._stopped_result(step, "interaction_unavailable")

    def _step_once(self, step: int, revision: int | None, attempt: int) -> StepResult:
        task = self._task
        session = self._session
        assert task is not None and session is not None

        # 1. 截屏
        try:
            screenshot = self.device.screenshot()
        except Exception as exc:
            self._checkpoint(revision)
            logger.error("screenshot failed: %s", exc)
            session.mark_aborted(f"screenshot_failed: {exc}")
            self._finished = True
            # 创建一个空白图片占位
            from PIL import Image as _Image
            screenshot = _Image.new("RGB", (1080, 1920), (0, 0, 0))
            return StepResult(
                step=step, screenshot=screenshot, screenshot_path=None,
                prompt_text="", raw_output="", reasoning_content="",
                action=Action(type=ACTION_WAIT),
                screen_summary="", action_summary=f"截图失败: {exc}",
                execution_success=False, notes=[f"screenshot_failed: {exc}"],
                usage=None, reasoning_time=0.0, execution_time=0.0,
                terminal=True, terminal_reason=f"screenshot_failed: {exc}",
            )

        # 降分辨率:上传给 VLM、落盘日志统一用这张 720P 图。坐标走归一化,
        # 设备层用真实分辨率换算像素,缩放不影响点击精度,只省带宽与磁盘。
        self._checkpoint(revision)
        screenshot = downscale(screenshot)
        screenshot_path = session.save_screenshot(step, screenshot, attempt)

        self._emit(STEP_SCREENSHOT_TAKEN, step=step, screenshot=screenshot)

        # 2. 推理
        self._emit(STEP_REASONING_STARTED, step=step)
        t0 = time.perf_counter()
        self._checkpoint(revision)
        try:
            instruction = task.instruction
            if self._interaction_context:
                instruction += "\n\n用户补充（以用户回答为准）：\n" + "\n".join(self._interaction_context)
            out = self.reasoner.predict(instruction, screenshot, session.history)
        except VLMAPIError as exc:
            self._checkpoint(revision)
            from .action import ActionOutput

            reason = f"reasoning_failed: {api_failure_code(exc)}: {exc}"
            logger.error("%s", reason)
            reasoning_time = time.perf_counter() - t0
            out = ActionOutput(
                action=Action(type=ACTION_WAIT), raw_output=str(exc),
                action_summary="模型调用失败，任务终止",
            )
            session.record_step(
                step, out, usage_already_counted=True, execution_success=False, notes=[reason],
                screenshot_path=screenshot_path, reasoning_time=reasoning_time,
            )
            session.mark_aborted(reason)
            self._finished = True
            return StepResult(
                step=step, screenshot=screenshot, screenshot_path=screenshot_path,
                prompt_text="", raw_output=str(exc), reasoning_content="",
                action=out.action, screen_summary="", action_summary=out.action_summary,
                execution_success=False, notes=[reason], usage=None,
                reasoning_time=reasoning_time, execution_time=0.0,
                terminal=True, terminal_reason=reason,
            )
        reasoning_time = time.perf_counter() - t0
        session.account_prediction(out.usage)
        session.record_interaction({"type": "model_decision", "step": step,
                                    "action": out.action.type, "parameters": out.action.parameters,
                                    "raw_output": out.raw_output, "screenshot": str(screenshot_path)})
        if self.control and self.control.snapshot() != ("running", revision):
            session.record_interaction({
                "type": "held_decision", "step": step, "action": out.action.type,
                "parameters": out.action.parameters, "raw_output": out.raw_output,
                "screenshot": str(screenshot_path), "executed": False,
            })
        self._checkpoint(revision)
        self._emit(
            STEP_REASONING_DONE,
            step=step,
            action=out.action,
            reasoning_time=reasoning_time,
            prompt_text=out.prompt_text,
            raw_output=out.raw_output,
            reasoning_content=out.reasoning_content,
            screen_summary=out.screen_summary,
            action_summary=out.action_summary,
            usage=out.usage,
        )

        logger.info(
            "[step %d] action=%s params=%s (%.1fs)",
            step, out.action.type, out.action.parameters, reasoning_time,
        )

        if out.action.type in (ACTION_ASK_USER, ACTION_TAKE_OVER):
            if self.interaction is None:
                raise InteractionUnavailable()
            request = {"type": out.action.type, **out.action.parameters}
            session.record_interaction({**request, "step": step})
            reply = self.interaction(request)
            if self.control:
                self.control.snapshot()  # Drain timestamped question/takeover boundaries before recording the step.
            if reply.get("status") == "stopped":
                raise RunStopped()
            interaction_notes = []
            if out.action.type == ACTION_ASK_USER and reply.get("status") == "answered":
                answer = str(reply.get("answer", "")).strip()
                if answer:
                    self._interaction_context.append(
                        f"问题：{out.action.parameters['question']}\n回答：{answer}"
                    )
                    session.record_interaction({"type": "user_answer", "step": step,
                                                "question": out.action.parameters["question"],
                                                "answer": answer})
                    interaction_notes.append(f"问题：{out.action.parameters['question']}\n回答：{answer}")
            session.record_step(step, out, usage_already_counted=True, execution_success=None,
                                screenshot_path=screenshot_path, reasoning_time=reasoning_time,
                                notes=interaction_notes)
            if step >= task.max_steps:
                session.mark_aborted("max_steps_reached")
                self._finished = True
            return StepResult(step, screenshot, screenshot_path, out.prompt_text, out.raw_output,
                              out.reasoning_content, out.action, out.screen_summary, out.action_summary,
                              None, interaction_notes, out.usage, reasoning_time, 0.0, self._finished,
                              "max_steps_reached" if self._finished else None)

        # 3. COMPLETE 不需要 guard,也不执行任何设备动作
        if out.action.type in (ACTION_COMPLETE, ACTION_ANSWER):
            failed = out.action.parameters.get("status") == "failed"
            terminal_reason = (out.action.parameters.get("reason") or "model_unable") if failed else "completed"
            if failed and terminal_reason not in ("model_unable", "app_not_installed", "blacklisted_app"):
                terminal_reason = "model_unable"
            session.record_step(
                step, out, usage_already_counted=True, execution_success=not failed,
                screenshot_path=screenshot_path,
                reasoning_time=reasoning_time, execution_time=0.0,
            )
            if failed:
                session.mark_aborted(str(terminal_reason))
            else:
                session.set_answer(out.action.parameters, step)
                session.mark_completed()
            self._finished = True
            logger.info("task ended at step %d: %s", step, terminal_reason)
            return StepResult(
                step=step, screenshot=screenshot, screenshot_path=screenshot_path,
                prompt_text=out.prompt_text, raw_output=out.raw_output,
                reasoning_content=out.reasoning_content,
                action=out.action, screen_summary=out.screen_summary,
                action_summary=out.action_summary, execution_success=not failed,
                notes=[], usage=out.usage,
                reasoning_time=reasoning_time, execution_time=0.0,
                terminal=True, terminal_reason=terminal_reason,
            )

        # 4. 敏感动作拦截
        if self.guard.needs_confirmation(task, out):
            approved = self.guard.ask(out, screenshot_path=str(screenshot_path))
            session.record_interaction({"type": "confirmation", "step": step,
                "action": out.action.type, "parameters": out.action.parameters,
                "screenshot": str(screenshot_path), **self.guard.last_decision})
            self._checkpoint(revision)
            if not approved:
                notes = ["user_denied_sensitive_action"]
                session.record_step(
                    step, out, usage_already_counted=True, execution_success=None, notes=notes,
                    screenshot_path=screenshot_path,
                    reasoning_time=reasoning_time, execution_time=0.0,
                )
                session.mark_aborted("user_denied")
                self._finished = True
                return StepResult(
                    step=step, screenshot=screenshot, screenshot_path=screenshot_path,
                    prompt_text=out.prompt_text, raw_output=out.raw_output,
                    reasoning_content=out.reasoning_content,
                    action=out.action, screen_summary=out.screen_summary,
                    action_summary=out.action_summary, execution_success=None,
                    notes=notes, usage=out.usage,
                    reasoning_time=reasoning_time, execution_time=0.0,
                    terminal=True, terminal_reason="user_denied",
                )

        # 5. 执行
        notes: list[str] = []
        success: bool | None
        self._emit(STEP_EXECUTING, step=step, action=out.action)
        t1 = time.perf_counter()
        try:
            self._check_takeover()
            self._checkpoint(revision)
            self._execute(out.action)
            success = True
        except (RunStopped, ReobserveRequired):
            raise
        except OpenAppNotFound as exc:
            self._open_miss_count += 1
            if self._open_miss_count >= self.max_open_misses:
                # 多次反馈仍未命中,升级为视觉兜底
                notes.append(self._arm_visual_fallback(exc.request, go_home=True))
            elif exc.suggestions:
                names = "、".join(exc.suggestions)
                notes.append(
                    f"OPEN '{exc.request}' 未匹配到应用。本机相似应用名:{names}。"
                    f"下一步请从中挑一个准确名字重新 OPEN;都不相关时,"
                    f"改用更短的核心关键词重新 OPEN(系统会按关键词搜索)。"
                )
            else:
                notes.append(
                    f"OPEN '{exc.request}' 未匹配到应用,也没有相似候选。"
                    f"请改用更短的核心关键词重新 OPEN(系统会按关键词搜索)。"
                )
            success = True
        except OpenAppNeedsVisual as exc:
            notes.append(self._arm_visual_fallback(exc.request))
            success = True
        except DeviceError as exc:
            self._checkpoint(revision)
            logger.warning("device error at step %d: %s", step, exc)
            notes.append(f"device_error: {exc}")
            success = False
        except Exception as exc:
            self._checkpoint(revision)
            logger.exception("unexpected error at step %d", step)
            notes.append(f"unexpected_error: {type(exc).__name__}: {exc}")
            success = False
        execution_time = time.perf_counter() - t1

        # 等待手机界面响应动作后稳定(页面跳转/动画/内容加载),
        # 避免下一轮截图拿到旧画面导致模型误判重复操作。
        if success and out.action.type not in (ACTION_WAIT, ACTION_COMPLETE):
            self._sleep(self.action_settle_seconds)

        # 6. 视觉兜底命中检测
        if self._pending_visual_request and out.action.type != ACTION_OPEN:
            current = self._safe_current_app()
            if current and current != self._visual_baseline_app:
                try:
                    self.device.learn_app_from_visual(self._pending_visual_request, current)
                    notes.append(f"visual_fallback_learned: {self._pending_visual_request} -> {current}")
                except Exception as exc:
                    logger.warning("learn_app_from_visual failed: %s", exc)
                self._pending_visual_request = None
                self._visual_baseline_app = None

        # 7. 记录
        session.record_step(
            step, out, usage_already_counted=True, execution_success=success, notes=notes,
            screenshot_path=screenshot_path,
            reasoning_time=reasoning_time, execution_time=execution_time,
        )

        # 8. 检查终止条件
        terminal = False
        terminal_reason: str | None = None

        if self.control and self.control.snapshot()[0] == "stopped":
            session.mark_aborted("user_stopped")
            terminal = True
            terminal_reason = "user_stopped"
        elif session.consecutive_failures() >= self.max_consecutive_failures:
            logger.warning("too many consecutive failures, abort")
            session.mark_aborted("consecutive_failures")
            terminal = True
            terminal_reason = "consecutive_failures"
        elif session.consecutive_identical_actions() >= self.max_consecutive_identical_actions:
            logger.warning(
                "stuck in loop: same action repeated %d times, abort",
                session.consecutive_identical_actions(),
            )
            session.mark_aborted("stuck_loop")
            terminal = True
            terminal_reason = "stuck_loop"
        elif step >= task.max_steps:
            session.mark_aborted("max_steps_reached")
            terminal = True
            terminal_reason = "max_steps_reached"

        if terminal:
            self._finished = True

        return StepResult(
            step=step, screenshot=screenshot, screenshot_path=screenshot_path,
            prompt_text=out.prompt_text, raw_output=out.raw_output,
            reasoning_content=out.reasoning_content,
            action=out.action, screen_summary=out.screen_summary,
            action_summary=out.action_summary, execution_success=success,
            notes=notes, usage=out.usage,
            reasoning_time=reasoning_time, execution_time=execution_time,
            terminal=terminal, terminal_reason=terminal_reason,
        )

    def run(self, task: Task) -> RunResult:
        """连续执行直到任务结束。

        等价于 start() + 循环调 step(),与重构前行为一致。
        CLI 入口使用此方法。
        """
        self.start(task)
        while not self._finished:
            self.step()
        return self._session.summarize()  # type: ignore[union-attr]

    @property
    def session(self) -> Session | None:
        """当前 Session,供外部(如调试器)读取状态。"""
        return self._session

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def current_step(self) -> int:
        return self._current_step

    # ======================== 内部 ========================

    def _record_control_event(self, event: dict) -> None:
        assert self._session is not None
        self._session.record_interaction({"step": self._current_step, **event})

    def _checkpoint(self, revision: int | None = None) -> int | None:
        current = self.control.checkpoint(revision) if self.control else None
        set_revision = getattr(self.device, "set_control_revision", None)
        if current is not None and callable(set_revision):
            set_revision(current)
        return current

    def _sleep(self, seconds: float) -> None:
        if self.control:
            self.control.sleep(seconds)
        else:
            time.sleep(seconds)

    def _check_takeover(self) -> None:
        detect = getattr(self.device, "takeover_reason", None)
        reason = detect() if callable(detect) else None
        if not isinstance(reason, str) or not reason.strip():
            return
        if self.interaction is None:
            raise InteractionUnavailable()
        assert self._session is not None
        self._session.record_interaction({"type": "sensitive_screen", "reason": reason})
        reply = self.interaction({"type": "TAKE_OVER", "reason": reason})
        if reply.get("status") == "stopped":
            raise RunStopped()
        raise ReobserveRequired()

    def _stopped_result(self, step: int, reason: str = "user_stopped") -> StepResult:
        from PIL import Image

        assert self._session is not None
        if self.control:
            self.control.snapshot()
        self._session.mark_aborted(reason)
        self._session.record_interaction({"type": reason, "step": step})
        self._finished = True
        return StepResult(step, Image.new("RGB", (1, 1)), None, "", "", "",
                          Action(type=ACTION_WAIT), "", "用户终止任务" if reason == "user_stopped" else "当前入口不支持交互，请使用安卓 App", None, [], None,
                          0.0, 0.0, True, reason)

    def _emit(self, event_type: str, **data: Any) -> None:
        """向 EventBus 发射事件(如果已配置)。"""
        if self._event_bus:
            self._event_bus.emit(event_type, **data)

    def _arm_visual_fallback(self, requested: str, go_home: bool = False) -> str:
        """武装视觉兜底状态,返回写入历史的 note 文本。

        go_home=True 时先回桌面(OpenAppNotFound 升级路径;
        OpenAppNeedsVisual 路径由 AppLauncher 自己回桌面)。
        """
        if go_home:
            try:
                self.device.go_home()
            except Exception as exc:
                logger.warning("go_home before visual fallback failed: %s", exc)
        self._pending_visual_request = requested
        self._visual_baseline_app = self._safe_current_app()
        logger.info(
            "visual fallback armed: request=%r baseline=%s",
            self._pending_visual_request, self._visual_baseline_app,
        )
        return (
            f"❗ OPEN '{requested}' 失败(视觉兜底):应用索引中找不到该应用,"
            f"系统已回桌面。本步绝对不要再 OPEN,必须 CLICK 桌面图标"
            f"(找不到时 SCROLL 水平翻页或上滑打开应用抽屉)。"
        )

    def _safe_current_app(self) -> str | None:
        try:
            return self.device.current_app()
        except Exception as exc:
            logger.warning("device.current_app() failed: %s", exc)
            return None

    def _execute(self, action: Action) -> None:
        if action.type == ACTION_CLICK:
            x, y = action.parameters["point"]
            self.device.click(int(x), int(y))
        elif action.type == ACTION_TYPE:
            self.device.type_text(action.parameters["text"])
        elif action.type == ACTION_SCROLL:
            start = tuple(action.parameters["start_point"])
            end = tuple(action.parameters["end_point"])
            self.device.scroll(start, end)
        elif action.type == ACTION_OPEN:
            self.device.open_app(action.parameters["app_name"])
        elif action.type == ACTION_BACK:
            self.device.back()
        elif action.type == ACTION_WAIT:
            seconds = action.parameters.get("seconds", 1.5)
            seconds = max(0.5, min(5.0, float(seconds)))  # 兜底:0.5-5 秒
            logger.info("WAIT %.1fs", seconds)
            self._sleep(seconds)
        elif action.type == ACTION_COMPLETE:
            pass
        else:
            raise DeviceError(f"unknown action type: {action.type}")


class InteractionUnavailable(Exception):
    """A noninteractive host must stop safely rather than guess or claim completion."""
