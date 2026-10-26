"""On-device 任务执行入口:组装 Runner 并逐步执行。

Phase 1 由 diag/TaskRunActivity 无 UI 驱动;Phase 2 起由前台 Service + Compose UI
经同一入口驱动(敏感动作确认回调换成 UI 弹窗)。
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from dataclasses import asdict


logger = logging.getLogger(__name__)

_LOGGING_CONFIGURED = False


def _ensure_logging() -> None:
    """把 Python logging 输出到 stderr(Chaquopy 会转发到 logcat)。"""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(message)s",
    )
    _LOGGING_CONFIGURED = True


def run_task(
    instruction: str,
    config_json: str,
    step_callback=None,
    confirm_callback=None,
    progress_callback=None,
    control_callback=None,
    interaction_callback=None,
) -> str:
    """执行一次自然语言任务,返回 JSON 结果摘要。

    Args:
        instruction:      用户任务指令
        config_json:      运行配置 JSON:
                          {"api_key": 必填, "base_url"/"model_id"/
                           "reasoning_effort"/"max_steps": 可选}
        step_callback:    每步结束回调 callback(step_json: str),供 Kotlin 侧展示进度
        confirm_callback: 敏感动作确认回调 callback(message: str) -> bool;
                          None 时默认拒绝(安全兜底)
        progress_callback: 可选阶段回调 callback(progress_json: str)，不包含截图或凭据
    """
    _ensure_logging()
    try:
        return _run_task(
            instruction, json.loads(config_json), step_callback, confirm_callback, progress_callback,
            control_callback, interaction_callback,
        )
    except Exception:
        return json.dumps(
            {"status": "error", "detail": traceback.format_exc()},
            ensure_ascii=False,
        )


def _create_reasoner(config: dict):
    """Legacy configs stay on Doubao; credentials never cross providers implicitly."""
    name = config.get("reasoner", "doubao")
    if name == "doubao":
        from seetouch.reasoning.doubao import DoubaoConfig, DoubaoReasoner

        kwargs = {"api_key": config["api_key"], "max_retries": 0,
                  "timeout": float(config.get("timeout", 60))}
        for key in ("model_id", "api_url", "thinking_mode"):
            if config.get(key):
                kwargs[key] = config[key]
        return DoubaoReasoner(DoubaoConfig(**kwargs))
    if name == "openai":
        from seetouch.reasoning.openai import OpenAIConfig, OpenAIReasoner

        kwargs = {"api_key": config["api_key"], "model_id": config.get("model_id", ""),
                  "max_retries": 0}
        for key in ("base_url", "reasoning_effort", "api_mode"):
            if config.get(key):
                kwargs[key] = config[key]
        kwargs["timeout"] = float(config.get("timeout", 60))
        return OpenAIReasoner(OpenAIConfig(**kwargs))
    raise ValueError(f"Unsupported Android reasoner: {name}")


def _notify_progress(callback, phase: str, step: int, action=None, action_summary="") -> None:
    if callback is None:
        return
    try:
        _call(callback, json.dumps({
            "phase": phase, "step": step,
            "action": action.type if action is not None else "",
            "action_summary": action_summary,
        }, ensure_ascii=False))
    except Exception:
        # Display failures must not change the task's actions or completion semantics.
        logger.warning("progress callback failed", exc_info=True)


def _progress_bus(callback):
    from seetouch.core.event_bus import (
        EventBus, STEP_EXECUTING, STEP_REASONING_DONE, STEP_REASONING_STARTED,
    )

    bus = EventBus()
    bus.subscribe(STEP_REASONING_STARTED, lambda step, **_: _notify_progress(
        callback, "thinking", step,
    ))
    bus.subscribe(STEP_REASONING_DONE, lambda step, action, action_summary="", **_: _notify_progress(
        callback, "checking", step, action, action_summary,
    ))
    bus.subscribe(STEP_EXECUTING, lambda step, action, **_: _notify_progress(
        callback, "executing", step, action,
    ))
    return bus


def _run_task(instruction, config: dict, step_callback, confirm_callback, progress_callback=None,
              control_callback=None, interaction_callback=None) -> str:
    from com.seetouch.app.bridge import DeviceBridge  # type: ignore[import-not-found]

    from seetouch.core.runner import Runner
    from seetouch.core.control import ExecutionControl, RunStopped
    from seetouch.core.task import Task
    from seetouch.device.android_native.controller import NativeAndroidController
    from seetouch.safety.guard import Guard
    from seetouch.memory import MemoryStore

    runs_dir = os.path.join(str(DeviceBridge.filesDir()), "runs")

    reasoner = _create_reasoner(config)
    max_steps = int(config.get("max_steps") or 45)

    def prompt(message: str) -> bool:
        if confirm_callback is None:
            logger.warning("sensitive action with no confirm_callback -> deny")
            return False
        return bool(_call(confirm_callback, message))

    def confirm_request(request: dict) -> dict | bool:
        if confirm_callback is None:
            return {"approved": False, "choice": "unavailable"}
        response = _call(confirm_callback, json.dumps(request, ensure_ascii=False))
        if isinstance(response, bool):
            return response
        return json.loads(str(response))

    device = NativeAndroidController()
    _notify_progress(progress_callback, "starting", 0)
    # 先回桌面:agent 跟手机同机运行,不先退到后台的话
    # 首张截图会是 SeeTouch 自己的界面,模型会误判为"应用正在处理"而反复 WAIT
    control = ExecutionControl(lambda: json.loads(str(_call(control_callback, "{}")))) if control_callback else None
    if control:
        try:
            device.set_control_revision(control.checkpoint())
            if not config.get("start_from_current", False):
                device.go_home()
        except RunStopped:
            pass
        except Exception:
            # A pause can race the initial HOME. Runner will wait/reobserve before any work.
            if control.snapshot()[0] == "running":
                raise
    else:
        if not config.get("start_from_current", False):
            device.go_home()

    def interact(request: dict) -> dict:
        if interaction_callback is None:
            return {"status": "stopped"}
        return json.loads(str(_call(interaction_callback, json.dumps(request, ensure_ascii=False))))

    runner = Runner(
        device=device,
        reasoner=reasoner,
        guard=Guard(prompt_fn=prompt, request_fn=confirm_request),
        runs_dir=runs_dir,
        event_bus=_progress_bus(progress_callback) if progress_callback is not None else None,
        control=control, interaction=interact,
        memory_store=MemoryStore(os.path.join(str(DeviceBridge.filesDir()), "agent_memory.json")),
        task_timeout_seconds=(
            float(config["task_timeout_seconds"])
            if float(config.get("task_timeout_seconds") or 0) > 0 else None
        ),
        max_model_retries=int(config.get("max_model_retries", 1)),
    )

    task = Task(instruction=instruction, max_steps=max_steps,
                **({"task_id": config["task_id"]} if config.get("task_id") else {}))
    runner.start(task)
    try:
        next_step = 1
        while not runner.is_finished:
            _notify_progress(progress_callback, "capturing", next_step)
            result = runner.step()
            if step_callback is not None:
                _call(step_callback, json.dumps(_step_summary(result), ensure_ascii=False))
            next_step += 1

        summary = runner.session.summarize()
        return json.dumps(
            {
                **asdict(summary),
                "completed": summary.completed,
                "aborted_reason": summary.aborted_reason,
                "total_steps": summary.total_steps,
                "task_id": task.task_id,
                "runs_dir": runs_dir,
                "tokens": {
                    "input": summary.total_input_tokens,
                    "output": summary.total_output_tokens,
                },
            },
            ensure_ascii=False,
        )

    finally:
        if control:
            control.snapshot()
        client = getattr(reasoner, "_client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("closing model client failed")


def _call(cb, arg):
    """兼容两种回调:Python callable 直接调;Kotlin lambda(Function1)调 invoke。"""
    if callable(cb):
        return cb(arg)
    return cb.invoke(arg)


def _step_summary(result) -> dict:
    return {
        "step": result.step,
        "action": result.action.type,
        "parameters": result.action.parameters,
        "action_summary": result.action_summary,
        "screen_summary": result.screen_summary,
        "success": result.execution_success,
        "notes": result.notes,
        "terminal": result.terminal,
        "terminal_reason": result.terminal_reason,
        "reasoning_time": round(result.reasoning_time, 2),
        "screenshot_path": str(result.screenshot_path) if result.screenshot_path else None,
    }
