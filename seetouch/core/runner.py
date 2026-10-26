"""主循环 Runner:把 device / reasoner / guard / session 串成闭环。

支持两种消费方式:
  - run(task):连续执行直到任务结束(CLI 用)
  - start(task) + 循环调 step():逐步执行(调试器用)
"""

from __future__ import annotations

import logging
import hashlib
import time
from pathlib import Path
from typing import Any
from collections.abc import Callable
from .control import ExecutionControl, ReobserveRequired, RunStopped
from .outcome import RETRYABLE_API_ERRORS, api_failure_code

from .event_bus import (
    EventBus,
    STEP_EXECUTING,
    STEP_REASONING_DONE,
    STEP_REASONING_STARTED,
    STEP_SCREENSHOT_TAKEN,
)
from ..core.action import (
    ACTION_CLICK,
    ACTION_LONG_PRESS,
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
from ..harness import (
    DEFAULT_GROUNDING_RADIUS,
    PinnedInputs,
    LoopPolicy,
    Observation,
    ProgressLedger,
    RunBudget,
    StepEntry,
    build_observation,
    ground_action,
    validate_action,
)
from ..perception.screen import downscale
from ..reasoning.base import Reasoner
from ..safety.guard import Guard
from .session import RunResult, Session, StepResult
from .task import Task
from .exceptions import VLMAPIError
from ..memory import MemoryStore
from ..memory.learning import finish_learning, memory_prompt


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
        max_consecutive_identical_actions: int = 5,
        max_open_misses: int = 3,
        event_bus: EventBus | None = None,
        action_settle_seconds: float = 1.0,
        control: ExecutionControl | None = None,
        interaction: Callable[[dict], dict] | None = None,
        memory_store: MemoryStore | None = None,
        task_timeout_seconds: float | None = None,
        max_model_retries: int = 1,
        model_retry_backoff_seconds: float = 2.0,
        max_idle_steps: int = 8,
        enable_click_grounding: bool = True,
        click_grounding_radius: float = DEFAULT_GROUNDING_RADIUS,
        max_tokens: int | None = None,
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
        self.memory_store = memory_store
        if task_timeout_seconds is not None and task_timeout_seconds <= 0:
            raise ValueError("task_timeout_seconds must be positive or None")
        if max_model_retries < 0:
            raise ValueError("max_model_retries must be >= 0")
        if model_retry_backoff_seconds < 0:
            raise ValueError("model_retry_backoff_seconds must be >= 0")
        if max_tokens is not None and max_tokens <= 0:
            raise ValueError("max_tokens must be positive or None")
        self.task_timeout_seconds = task_timeout_seconds
        self.max_model_retries = max_model_retries
        self.model_retry_backoff_seconds = model_retry_backoff_seconds
        self.max_idle_steps = max_idle_steps
        self.enable_click_grounding = enable_click_grounding
        self.click_grounding_radius = click_grounding_radius
        self._interaction_context: list[str] = []
        self._pinned_inputs = PinnedInputs()

        # harness 组件：观测 / 账本 / 预算 / 策略（见 seetouch.harness）
        self._observation: Observation | None = None
        self._ledger = ProgressLedger()
        self._budget = RunBudget(max_steps=None, max_seconds=task_timeout_seconds, max_tokens=max_tokens)
        self._policy = LoopPolicy(max_idle_steps=max_idle_steps)
        self._last_hint_code: str | None = None

        # 运行状态(start() 初始化,step() 推进)
        self._session: Session | None = None
        self._task: Task | None = None
        self._current_step: int = 0
        self._finished: bool = True
        self._pending_visual_request: str | None = None
        self._visual_baseline_app: str | None = None
        self._open_miss_count = 0
        self._deadline: float | None = None
        self._last_screen_signature: str | None = None
        self._no_change_streak = 0
        self._completion_rejections = 0

    # ======================== 公开 API ========================

    def start(self, task: Task) -> None:
        """初始化一次任务执行。后续通过 step() 逐步推进。"""
        self._task = task
        config = getattr(self.reasoner, "_config", None)
        model_id = getattr(config, "model_id", None)
        if not isinstance(model_id, str):
            model_id = None
        self._session = Session(
            task,
            base_dir=self.runs_dir,
            metadata={
                "reasoner": type(self.reasoner).__name__,
                "model_id": model_id,
            },
        )
        self._interaction_context = []
        self._pinned_inputs.clear()
        if self.control:
            self.control.event_sink = self._record_control_event
        self._current_step = 0
        self._finished = False
        self._pending_visual_request = None
        self._visual_baseline_app = None
        self._open_miss_count = 0
        self._last_screen_signature = None
        self._no_change_streak = 0
        self._completion_rejections = 0
        self._deadline = (
            time.monotonic() + self.task_timeout_seconds
            if self.task_timeout_seconds is not None else None
        )
        self._observation = None
        self._ledger.reset()
        self._budget.start()
        self._last_hint_code = None
        if self.memory_store:
            try:
                memories = self.memory_store.retrieve(task.instruction)
                self._session.used_memory_ids = [m["id"] for m in memories]
                self._session.record_interaction({"type": "memory_loaded", "step": 0,
                                                  "memory_ids": self._session.used_memory_ids})
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("local memory unavailable; continuing without memory")
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

        if self._deadline is not None and time.monotonic() >= self._deadline:
            return self._timeout_result(self._current_step + 1)
        self._current_step += 1
        step = self._current_step
        attempt = 0
        while True:
            try:
                revision = self._checkpoint()
                self._check_takeover()
                result = self._step_once(step, revision, attempt)
                if result.terminal and self.memory_store:
                    try:
                        finish_learning(self.memory_store, self._session, result.action)
                    except (OSError, ValueError, KeyError, TypeError):
                        self._session.learning_status = "error"
                        logger.warning("experience save failed; task result preserved")
                return result
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
        # 一帧观测：结构节点 + 签名。prompt、trace、点击校准共用这一份数据。
        self._observation = self._build_observation(screenshot)
        ui_context = self._observation.render() or self._read_ui_context()
        unchanged = self._observe_screen_change(screenshot, ui_context)

        self._emit(STEP_SCREENSHOT_TAKEN, step=step, screenshot=screenshot)

        # 2. 推理
        self._emit(STEP_REASONING_STARTED, step=step)
        t0 = time.perf_counter()
        self._checkpoint(revision)
        try:
            instruction = task.instruction
            if self.memory_store:
                try:
                    instruction += memory_prompt(self.memory_store, session.used_memory_ids)
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            if len(self._pinned_inputs):
                # 用户明确给出的补充：不参与历史压缩，永远原样出现在指令里
                instruction += "\n\n" + self._pinned_inputs.render()
            remaining = max(0, task.max_steps - step + 1)
            instruction += f"\n\n任务进度：已完成 {step - 1} 步，剩余最多 {remaining} 步。"
            if ui_context:
                instruction += (
                    "\n\n系统提供的当前界面控件（坐标是 0-1000 归一化中心；"
                    "点击优先使用对应控件的 center）：\n" + ui_context
                )
            hint = self._policy.evaluate(
                step=step,
                unchanged_streak=unchanged,
                repeated_streak=self._ledger.repeated_streak(),
            )
            if hint is not None and hint.action in ("nudge", "escalate"):
                self._last_hint_code = hint.code
                hint_text = hint.text
                if hint.code.startswith("unchanged") and session.history:
                    hint_text += f"上一步是 {session.history[-1].action.type}。"
                instruction += "\n\n" + hint_text
            out = self._predict_with_retry(instruction, screenshot, session, step, revision)
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
                ui_context=ui_context,
                screen_unchanged_streak=unchanged,
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

        # 落点校准：把"差一点点"的点击吸附到真实控件中心，并把诊断写进 trace。
        pre_notes: list[str] = []
        try:
            grounding = ground_action(
                out.action,
                self._observation,
                radius=self.click_grounding_radius,
                enabled=self.enable_click_grounding,
            )
        except Exception as exc:  # 校准失败绝不能影响主流程
            logger.warning("click grounding failed: %s", exc)
            grounding = None
        if grounding is not None:
            if grounding.moved:
                session.record_interaction({
                    "type": "click_grounded", "step": step,
                    "from": list(out.action.parameters.get("point") or []),
                    "to": list(grounding.action.parameters.get("point") or []),
                    "node": grounding.label,
                })
                out.action = grounding.action
            if grounding.note:
                pre_notes.append(grounding.note)
        for problem in validate_action(out.action, self._observation):
            pre_notes.append(f"action_diagnostic: {problem}")

        session.account_prediction(out.usage)
        self._budget.consume_tokens(_usage_tokens(out.usage))
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
        if self._deadline is not None and time.monotonic() >= self._deadline:
            session.record_step(
                step, out, usage_already_counted=True, execution_success=None,
                notes=["task_timeout_before_action"], screenshot_path=screenshot_path,
                reasoning_time=reasoning_time,
                ui_context=ui_context,
                screen_unchanged_streak=unchanged,
            )
            return self._timeout_result(step, out, screenshot, screenshot_path)
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
                    pinned = f"问题：{out.action.parameters['question']}\n回答：{answer}"
                    self._interaction_context.append(pinned)
                    self._pinned_inputs.add(pinned)
                    session.record_interaction({"type": "user_answer", "step": step,
                                                "question": out.action.parameters["question"],
                                                "answer": answer})
                    interaction_notes.append(f"问题：{out.action.parameters['question']}\n回答：{answer}")
            session.record_step(step, out, usage_already_counted=True, execution_success=None,
                                screenshot_path=screenshot_path, reasoning_time=reasoning_time,
                                notes=interaction_notes, ui_context=ui_context,
                                screen_unchanged_streak=unchanged)
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
            if (
                out.action.type == ACTION_COMPLETE
                and not failed
                and self._premature_completion(task, session)
            ):
                self._completion_rejections += 1
                note = (
                    "拒绝过早完成：该任务包含多个步骤，但还没有执行任何目标界面的"
                    "点击/输入/滚动/返回操作。请继续完成剩余步骤。"
                )
                if self._completion_rejections >= 2:
                    session.record_step(
                        step, out, usage_already_counted=True, execution_success=False,
                        notes=[note, "repeated_premature_completion"],
                        screenshot_path=screenshot_path, reasoning_time=reasoning_time,
                        ui_context=ui_context, screen_unchanged_streak=unchanged,
                    )
                    session.mark_aborted("premature_completion")
                    self._finished = True
                    return StepResult(
                        step=step, screenshot=screenshot, screenshot_path=screenshot_path,
                        prompt_text=out.prompt_text, raw_output=out.raw_output,
                        reasoning_content=out.reasoning_content, action=out.action,
                        screen_summary=out.screen_summary, action_summary=out.action_summary,
                        execution_success=False, notes=[note], usage=out.usage,
                        reasoning_time=reasoning_time, execution_time=0.0,
                        terminal=True, terminal_reason="premature_completion",
                    )
                session.record_interaction({"type": "premature_completion", "step": step})
                session.record_step(
                    step, out, usage_already_counted=True, execution_success=None,
                    notes=[note], screenshot_path=screenshot_path,
                    reasoning_time=reasoning_time, ui_context=ui_context,
                    screen_unchanged_streak=unchanged,
                )
                return StepResult(
                    step=step, screenshot=screenshot, screenshot_path=screenshot_path,
                    prompt_text=out.prompt_text, raw_output=out.raw_output,
                    reasoning_content=out.reasoning_content, action=out.action,
                    screen_summary=out.screen_summary,
                    action_summary="拒绝过早完成，继续执行", execution_success=None,
                    notes=[note], usage=out.usage, reasoning_time=reasoning_time,
                    execution_time=0.0, terminal=False,
                )
            terminal_reason = (out.action.parameters.get("reason") or "model_unable") if failed else "completed"
            if failed and terminal_reason not in ("model_unable", "app_not_installed", "blacklisted_app"):
                terminal_reason = "model_unable"
            session.record_step(
                step, out, usage_already_counted=True, execution_success=not failed,
                screenshot_path=screenshot_path,
                reasoning_time=reasoning_time, execution_time=0.0,
                ui_context=ui_context,
                screen_unchanged_streak=unchanged,
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
                    ui_context=ui_context,
                    screen_unchanged_streak=unchanged,
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
        notes: list[str] = list(pre_notes)
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
        if unchanged >= 2:
            notes.append(f"界面已连续 {unchanged} 步未变化")
        session.record_step(
            step, out, usage_already_counted=True, execution_success=success, notes=notes,
            screenshot_path=screenshot_path,
            reasoning_time=reasoning_time, execution_time=execution_time,
            ui_context=ui_context,
            screen_unchanged_streak=unchanged,
        )
        self._ledger.record(StepEntry(
            step=step,
            action=str(out.action.type),
            parameters=dict(out.action.parameters),
            summary=(out.action_summary or "")[:80],
            outcome="ok" if success else "failed",
            note="; ".join(notes)[:160],
            screen_signature=(
                self._observation.signature if self._observation else ""
            ) or (self._last_screen_signature or ""),
        ))

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

        # 策略层兜底：空转 / 预算耗尽这类"不是失败但也不该继续"的情况
        if not terminal:
            hint = self._policy.evaluate(
                step=step,
                unchanged_streak=unchanged,
                repeated_streak=self._ledger.repeated_streak(),
                budget_reason=self._budget.exhausted(step),
            )
            if hint is not None and hint.action == "abort":
                self._last_hint_code = hint.code
                notes.append(hint.text)
                session.mark_aborted(hint.terminal_reason or hint.code)
                terminal = True
                terminal_reason = hint.terminal_reason or hint.code

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

    @property
    def ledger(self) -> ProgressLedger:
        """本次任务的进度账本（调试器 / 评测脚本读取）。"""
        return self._ledger

    @property
    def budget(self) -> RunBudget:
        """本次任务的预算账本。"""
        return self._budget

    @property
    def pinned_inputs(self) -> PinnedInputs:
        """用户明确给出的补充（永不压缩）。"""
        return self._pinned_inputs

    @property
    def observation(self) -> Observation | None:
        """最近一帧观测（调试用）。"""
        return self._observation

    # ======================== 内部 ========================

    def _record_control_event(self, event: dict) -> None:
        assert self._session is not None
        self._session.record_interaction({"step": self._current_step, **event})

    def _predict_with_retry(self, instruction, screenshot, session, step, revision):
        attempts = self.max_model_retries + 1
        for attempt in range(attempts):
            try:
                return self.reasoner.predict(instruction, screenshot, session.history)
            except VLMAPIError as exc:
                code = api_failure_code(exc)
                if code not in RETRYABLE_API_ERRORS or attempt + 1 >= attempts:
                    raise
                delay = self.model_retry_backoff_seconds * (2 ** attempt)
                session.record_interaction({
                    "type": "model_retry", "step": step, "attempt": attempt + 1,
                    "error_code": code, "delay_seconds": delay,
                })
                logger.warning(
                    "transient model error (%s), retrying in %.1fs (%d/%d)",
                    code, delay, attempt + 1, self.max_model_retries,
                )
                self._sleep(delay)
                self._checkpoint(revision)

    def _timeout_result(self, step, out=None, screenshot=None, screenshot_path=None) -> StepResult:
        from PIL import Image
        from .action import ActionOutput

        assert self._session is not None
        if out is None:
            out = ActionOutput(
                action=Action(type=ACTION_WAIT), raw_output="",
                action_summary="任务超时",
            )
        if screenshot is None:
            screenshot = Image.new("RGB", (1, 1))
        self._session.mark_aborted("task_timeout")
        self._finished = True
        self._session.record_interaction({"type": "task_timeout", "step": step})
        return StepResult(
            step=step, screenshot=screenshot, screenshot_path=screenshot_path,
            prompt_text="", raw_output="", reasoning_content="",
            action=out.action, screen_summary="", action_summary="任务超时",
            execution_success=None, notes=["task_timeout"], usage=None,
            reasoning_time=0.0, execution_time=0.0,
            terminal=True, terminal_reason="task_timeout",
        )

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

    def _read_ui_context(self) -> str:
        read = getattr(self.device, "ui_context", None)
        if not callable(read):
            return ""
        try:
            value = read()
            return value if isinstance(value, str) else ""
        except Exception as exc:
            logger.warning("ui_context failed: %s", exc)
            return ""

    def _device_screen_size(self, screenshot) -> tuple[int, int]:
        """设备真实分辨率（节点 bounds 用的是像素，必须按它归一化）。"""
        try:
            size = self.device.screen_size()
            width, height = int(size[0]), int(size[1])
            if width > 0 and height > 0:
                return (width, height)
        except Exception:
            pass
        try:
            return (int(screenshot.size[0]), int(screenshot.size[1]))
        except Exception:
            return (0, 0)

    def _build_observation(self, screenshot) -> Observation:
        """取这一帧的结构化观测；设备不支持时返回空观测（纯视觉链路照常工作）。"""
        screen = self._device_screen_size(screenshot)
        read = getattr(self.device, "ui_elements", None)
        if callable(read):
            try:
                elements = read()
            except Exception as exc:
                logger.warning("ui_elements failed: %s", exc)
                elements = None
            if isinstance(elements, list) and elements:
                try:
                    return build_observation(
                        elements=elements, screen_size=screen,
                    )
                except Exception as exc:
                    logger.warning("observation build failed: %s", exc)
        return Observation(screen_size=screen)

    def _premature_completion(self, task, session) -> bool:
        if not _instruction_is_multi_step(task.instruction):
            return False
        meaningful = {"CLICK", "LONG_PRESS", "TYPE", "SCROLL", "BACK"}
        return not any(record.action.type in meaningful for record in session.history)

    def _observe_screen_change(self, screenshot, ui_context: str) -> int:
        # 有结构节点时用结构签名（忽略焦点等瞬时抖动），否则退回文本/像素摘要
        signature = self._observation.signature if self._observation else ""
        if not signature:
            if ui_context:
                payload = ui_context.encode("utf-8")
            else:
                width, height = screenshot.size
                body = screenshot.convert("L").crop((0, int(height * 0.1), width, height))
                payload = body.resize((32, 32)).tobytes()
            signature = hashlib.sha1(payload).hexdigest()
        if signature == self._last_screen_signature:
            self._no_change_streak += 1
        else:
            self._no_change_streak = 1
            self._last_screen_signature = signature
        return self._no_change_streak

    def _execute(self, action: Action) -> None:
        if action.type == ACTION_CLICK:
            x, y = action.parameters["point"]
            self.device.click(int(x), int(y))
        elif action.type == ACTION_LONG_PRESS:
            x, y = action.parameters["point"]
            self.device.long_press(int(x), int(y))
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


def _usage_tokens(usage: dict[str, Any] | None) -> int:
    """从 usage 字典里取本步 token 总数（缺失字段按 0 计）。"""
    if not usage:
        return 0
    try:
        return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return 0


def _instruction_is_multi_step(instruction: str) -> bool:
    text = instruction or ""
    markers = ("然后", "再", "并", "进入", "开启", "关闭", "返回", "找到")
    return any(marker in text for marker in markers) or sum(
        text.count(verb) for verb in ("打开", "点击", "输入", "开启", "关闭")
    ) >= 2
