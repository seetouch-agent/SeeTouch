"""命令行入口。

用法:
    python -m seetouch run "<指令>"
    python -m seetouch run "<指令>" --serial <设备serial>
    python -m seetouch run "<指令>" --max-steps 30
    python -m seetouch debug
    python -m seetouch debug --port 8080
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from ..config import AppSettings, load_env
from ..core.runner import Runner
from ..core.task import Task
from ..device.android.controller import AndroidController
from ..logging_config import configure_logging
from ..reasoning.factory import (
    DEFAULT_DEBUG_REASONER, DEFAULT_REASONER, REASONER_NAMES, create_reasoner,
)
from ..safety.guard import Guard
from ..memory import MemoryStore


logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    load_env()
    settings = AppSettings.from_env()
    configure_logging(settings.log_level)

    if args.command == "run":
        return _cmd_run(args, settings)
    elif args.command == "debug":
        return _cmd_debug(args, settings)

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seetouch", description="Android GUI Agent")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="执行一条自然语言任务")
    p_run.add_argument("instruction", help="用户任务指令,如:在哔哩哔哩搜索采莲曲")
    p_run.add_argument("--serial", default=None, help="Android 设备 serial(多设备时使用)")
    p_run.add_argument("--max-steps", type=int, default=None, help="单任务最大步数(默认 45)")
    p_run.add_argument("--runs-dir", default=None, help="运行产物输出目录(默认 ./runs)")
    p_run.add_argument("--no-memory", action="store_true", help="本次不加载或积累本地记忆")
    p_run.add_argument(
        "--reasoner",
        choices=REASONER_NAMES,
        default=DEFAULT_REASONER,
        help="推理模型选择: doubao、gemini(默认) 或 openai(支持兼容中转站)",
    )

    p_debug = sub.add_parser("debug", help="启动图形化调试器")
    p_debug.add_argument("--port", type=int, default=5000, help="调试器服务端口(默认 5000)")
    p_debug.add_argument(
        "--reasoner", choices=REASONER_NAMES, default=DEFAULT_DEBUG_REASONER,
        help="推理后端: doubao(默认)、gemini 或 openai",
    )

    return parser


def _cmd_run(args: argparse.Namespace, settings: AppSettings) -> int:
    serial = args.serial or settings.device_serial
    runs_dir = args.runs_dir or settings.runs_dir
    max_steps = args.max_steps or settings.max_steps

    try:
        device = AndroidController(serial=serial)
    except Exception as exc:
        logger.error("init android device failed: %s", exc)
        print(f"[ERROR] init android device failed: {exc}", file=sys.stderr)
        return 1

    # 根据参数选择推理模型
    try:
        reasoner = create_reasoner(args.reasoner)
        logger.info("using %s reasoner", args.reasoner)
    except Exception as exc:
        logger.error("init reasoner failed: %s", exc)
        print(f"[ERROR] init reasoner failed: {exc}", file=sys.stderr)
        return 1

    runner = Runner(
        device=device,
        reasoner=reasoner,
        guard=Guard(),
        runs_dir=runs_dir,
        memory_store=None if args.no_memory else MemoryStore(Path.home() / ".seetouch" / "agent_memory.json"),
        max_consecutive_failures=int(os.environ.get("SEETOUCH_MAX_CONSECUTIVE_FAILURES", "2")),
        max_consecutive_identical_actions=int(
            os.environ.get("SEETOUCH_MAX_CONSECUTIVE_IDENTICAL_ACTIONS", "5")
        ),
        max_open_misses=int(os.environ.get("SEETOUCH_MAX_OPEN_MISSES", "3")),
        action_settle_seconds=float(os.environ.get("SEETOUCH_ACTION_SETTLE_SECONDS", "1.0")),
        task_timeout_seconds=(
            float(os.environ["SEETOUCH_TASK_TIMEOUT"])
            if float(os.environ.get("SEETOUCH_TASK_TIMEOUT", "0")) > 0 else None
        ),
        max_model_retries=int(os.environ.get("SEETOUCH_MAX_MODEL_RETRIES", "1")),
        # harness 升级项（见 docs/harness-design.md）
        max_idle_steps=int(os.environ.get("SEETOUCH_MAX_IDLE_STEPS", "8")),
        enable_click_grounding=os.environ.get("SEETOUCH_CLICK_GROUNDING", "1") not in ("0", "false", "no"),
        click_grounding_radius=float(os.environ.get("SEETOUCH_CLICK_GROUNDING_RADIUS", "60")),
        max_tokens=(
            int(os.environ["SEETOUCH_MAX_TOKENS"])
            if int(os.environ.get("SEETOUCH_MAX_TOKENS", "0")) > 0 else None
        ),
    )

    task = Task(instruction=args.instruction, max_steps=max_steps)
    result = runner.run(task)

    print()
    print("============== 任务结果 ==============")
    print(f"task_id:        {result.task_id}")
    print(f"completed:      {result.completed}")
    print(f"aborted_reason: {result.aborted_reason or '-'}")
    print(f"total_steps:    {result.total_steps}")
    print(f"tokens (in/out): {result.total_input_tokens}/{result.total_output_tokens}")
    print(f"runs_dir:       {result.runs_dir}")
    return 0 if result.completed else 1


def _cmd_debug(args: argparse.Namespace, settings: AppSettings) -> int:
    try:
        from ..debugger.app import run_server
    except ImportError as exc:
        print(
            f"[ERROR] 调试器依赖未安装: {exc}\n"
            f"请运行: pip install seetouch[debugger]",
            file=sys.stderr,
        )
        return 1

    run_server(port=args.port, settings=settings, reasoner_name=args.reasoner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
