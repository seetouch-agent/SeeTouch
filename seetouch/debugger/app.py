"""Flask + SocketIO 调试器服务。

启动后在浏览器中提供图形化调试界面:
  - 实时截图 + 动作标注
  - prompt / 模型输出 / 动作 / token 用量展示
  - 单步(Step)/ 连续(Run)/ 暂停(Pause)/ 停止(Stop)控制
  - 历史步骤回看
"""

from __future__ import annotations

import logging
import os
import webbrowser
from pathlib import Path

from flask import Flask, send_from_directory
from flask_socketio import SocketIO

from ..config import AppSettings, load_env
from ..core.event_bus import EventBus
from ..core.runner import Runner
from ..device.android.controller import AndroidController
from ..logging_config import configure_logging
from ..reasoning.factory import DEFAULT_REASONER, create_reasoner
from ..safety.guard import Guard
from .debug_session import DebugSession, StepData


logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    settings: AppSettings | None = None,
    reasoner_name: str = DEFAULT_REASONER,
) -> tuple[Flask, SocketIO]:
    """创建 Flask 应用和 SocketIO 实例。"""
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config["SECRET_KEY"] = os.urandom(24).hex()
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    # 延迟初始化的调试会话
    debug_session: DebugSession | None = None

    # ======================== HTTP 路由 ========================

    @app.route("/")
    def index():
        return send_from_directory(str(STATIC_DIR), "index.html")

    @app.route("/api/status")
    def status():
        if debug_session is None:
            return {"state": "idle", "steps": 0}
        return {
            "state": debug_session.state,
            "steps": len(debug_session.step_history),
        }

    # ======================== SocketIO 事件 ========================

    @socketio.on("connect")
    def on_connect():
        logger.info("client connected")
        state = debug_session.state if debug_session else "idle"
        socketio.emit("status", {"state": state})

    @socketio.on("start")
    def on_start(data):
        nonlocal debug_session

        instruction = data.get("instruction", "").strip()
        if not instruction:
            socketio.emit("error", {"message": "指令不能为空"})
            return

        max_steps = int(data.get("max_steps", 45))
        serial = data.get("serial") or (settings.device_serial if settings else None)

        try:
            # 初始化设备和推理器
            device = AndroidController(serial=serial)
            reasoner = create_reasoner(reasoner_name)

            # Guard 确认回调:通过 WebSocket 通知前端,阻塞等待回复
            # 注意:当前版本直接自动批准,避免阻塞复杂性。
            # 后续可以改为 WebSocket 双向确认。
            guard = Guard(prompt_fn=lambda msg: True)

            # 创建事件总线(生命周期与任务绑定)
            event_bus = EventBus()

            runner = Runner(
                device=device,
                reasoner=reasoner,
                guard=guard,
                runs_dir=settings.runs_dir if settings else "runs",
                event_bus=event_bus,
            )

            debug_session = DebugSession(runner, event_bus=event_bus)

            # 设置回调
            def on_step_result(step_data: StepData):
                socketio.emit("step_result", step_data.to_dict())

            def on_task_finished(summary: dict):
                socketio.emit("task_finished", summary)

            def on_error(message: str):
                socketio.emit("error", {"message": message})

            def on_state_change(state: str):
                socketio.emit("status", {"state": state})

            def on_step_progress(data: dict):
                socketio.emit("step_progress", data)

            def on_log(data: dict):
                socketio.emit("log", data)

            debug_session.on_step_result = on_step_result
            debug_session.on_task_finished = on_task_finished
            debug_session.on_error = on_error
            debug_session.on_state_change = on_state_change
            debug_session.on_step_progress = on_step_progress
            debug_session.on_log = on_log

            debug_session.start_task(instruction, max_steps=max_steps)
            socketio.emit("status", {"state": debug_session.state})
            logger.info("task started: %r", instruction)

        except Exception as exc:
            logger.exception("start task failed")
            socketio.emit("error", {"message": f"启动失败: {type(exc).__name__}: {exc}"})

    @socketio.on("step")
    def on_step():
        if debug_session is None:
            socketio.emit("error", {"message": "没有活跃的任务,请先输入指令并启动"})
            return
        try:
            debug_session.do_step()
            socketio.emit("status", {"state": debug_session.state})
        except RuntimeError as exc:
            socketio.emit("error", {"message": str(exc)})

    @socketio.on("run")
    def on_run():
        if debug_session is None:
            socketio.emit("error", {"message": "没有活跃的任务,请先输入指令并启动"})
            return
        try:
            debug_session.do_run()
            socketio.emit("status", {"state": debug_session.state})
        except RuntimeError as exc:
            socketio.emit("error", {"message": str(exc)})

    @socketio.on("pause")
    def on_pause():
        if debug_session is None:
            return
        debug_session.do_pause()
        socketio.emit("status", {"state": debug_session.state})

    @socketio.on("stop")
    def on_stop():
        nonlocal debug_session
        if debug_session is None:
            return
        debug_session.do_stop()
        socketio.emit("status", {"state": "idle"})
        debug_session = None

    @socketio.on("get_history")
    def on_get_history():
        if debug_session is None:
            socketio.emit("history", {"steps": []})
            return
        socketio.emit("history", {
            "steps": [s.to_dict() for s in debug_session.step_history]
        })

    return app, socketio


def run_server(
    port: int = 5000,
    settings: AppSettings | None = None,
    reasoner_name: str = DEFAULT_REASONER,
) -> None:
    """启动调试器 Web 服务。"""
    load_env()
    if settings is None:
        settings = AppSettings.from_env()
    configure_logging(settings.log_level)

    app, socketio = create_app(settings, reasoner_name=reasoner_name)

    url = f"http://localhost:{port}"
    logger.info("SeeTouch Debugger starting at %s", url)
    print(f"\n  SeeTouch Debugger: {url}\n")

    # 尝试自动打开浏览器
    try:
        webbrowser.open(url)
    except Exception:
        pass

    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
