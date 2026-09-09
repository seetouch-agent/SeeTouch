"""On-device 任务执行入口:组装 Runner 并逐步执行。

Phase 1 由 diag/TaskRunActivity 无 UI 驱动;Phase 2 起由前台 Service + Compose UI
经同一入口驱动(敏感动作确认回调换成 UI 弹窗)。
"""

from __future__ import annotations

import json
import logging
import os
import traceback


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
    """
    _ensure_logging()
    try:
        return _run_task(instruction, json.loads(config_json), step_callback, confirm_callback)
    except Exception:
        return json.dumps(
            {"status": "error", "detail": traceback.format_exc()},
            ensure_ascii=False,
        )


def _run_task(instruction, config: dict, step_callback, confirm_callback) -> str:
    from com.seetouch.app.bridge import DeviceBridge  # type: ignore[import-not-found]

    from seetouch.core.runner import Runner
    from seetouch.core.task import Task
    from seetouch.device.android_native.controller import NativeAndroidController
    from seetouch.reasoning.openai_compatible import (
        OpenAICompatibleConfig,
        OpenAICompatibleReasoner,
    )
    from seetouch.safety.guard import Guard

    runs_dir = os.path.join(str(DeviceBridge.filesDir()), "runs")

    reasoner_kwargs = {"api_key": config["api_key"]}
    for key in ("base_url", "model_id", "reasoning_effort"):
        if config.get(key):
            reasoner_kwargs[key] = config[key]
    max_steps = int(config.get("max_steps") or 45)

    def prompt(message: str) -> bool:
        if confirm_callback is None:
            logger.warning("sensitive action with no confirm_callback -> deny")
            return False
        return bool(_call(confirm_callback, message))

    device = NativeAndroidController()
    # 先回桌面:agent 跟手机同机运行,不先退到后台的话
    # 首张截图会是 SeeTouch 自己的界面,模型会误判为"应用正在处理"而反复 WAIT
    device.go_home()

    runner = Runner(
        device=device,
        reasoner=OpenAICompatibleReasoner(OpenAICompatibleConfig(**reasoner_kwargs)),
        guard=Guard(prompt_fn=prompt),
        runs_dir=runs_dir,
    )

    task = Task(instruction=instruction, max_steps=max_steps)
    runner.start(task)
    while not runner.is_finished:
        result = runner.step()
        if step_callback is not None:
            _call(step_callback, json.dumps(_step_summary(result), ensure_ascii=False))

    summary = runner.session.summarize()
    return json.dumps(
        {
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
    }
