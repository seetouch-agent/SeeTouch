"""回放某次 session:读 trace.jsonl 打印每一步。

用法:
    python seetouch/scripts/replay.py runs/<task_id>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def replay(session_dir: Path) -> int:
    trace_path = session_dir / "trace.jsonl"
    summary_path = session_dir / "summary.json"
    interactions_path = session_dir / "interactions.jsonl"
    if not trace_path.exists() and not interactions_path.exists():
        print(f"trace.jsonl not found in {session_dir}", file=sys.stderr)
        return 1

    print(f"=== Session: {session_dir} ===")

    for line in trace_path.read_text(encoding="utf-8").splitlines() if trace_path.exists() else []:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        step = rec.get("step", "?")
        atype = rec.get("action_type", "?")
        params = rec.get("parameters", {})
        scr = rec.get("screen_summary", "")
        act = rec.get("action_summary", "")
        success = rec.get("execution_success")
        notes = rec.get("notes") or []
        screenshot = rec.get("screenshot", "")

        print(f"\n--- Step {step}: {atype} {json.dumps(params, ensure_ascii=False)}")
        if scr:
            print(f"  屏幕: {scr}")
        if act:
            print(f"  操作: {act}")
        if success is False:
            print("  [x] 执行失败")
        elif success is True:
            print("  [v] 执行成功")
        if notes:
            for n in notes:
                print(f"  备注: {n}")
        if screenshot:
            print(f"  截图: {screenshot}")

    if interactions_path.exists():
        print("\n=== 控制与交互记录 ===")
        labels = {"paused": "已暂停", "running": "继续执行", "waiting_user": "等待回答",
                  "takeover_start": "开始人工接管", "takeover_end": "结束人工接管",
                  "stopped": "终止", "user_stopped": "任务已终止",
                  "ASK_USER": "追问", "user_answer": "用户回答", "TAKE_OVER": "请求人工接管",
                  "memory_loaded": "匹配本地记忆", "experience_saved": "保存操作经验"}
        for line in interactions_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                label = labels.get(event.get("type"))
                if label is None:
                    continue
                when = datetime.fromtimestamp(float(event["timestamp"])).isoformat(timespec="seconds")
            except (ValueError, TypeError, KeyError):
                continue
            detail = event.get("answer") or event.get("question") or event.get("reason") or ""
            if event.get("type") == "memory_loaded":
                detail = ", ".join(event.get("memory_ids", []))
            elif event.get("type") == "experience_saved":
                detail = event.get("memory_id", "")
            print(f"  {when} Step {event.get('step', '?')} {label} {detail}")

    if summary_path.exists():
        print("\n=== Summary ===")
        print(summary_path.read_text(encoding="utf-8"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="回放 seetouch session")
    parser.add_argument("session_dir", help="runs/<task_id> 目录路径")
    args = parser.parse_args()
    return replay(Path(args.session_dir))


if __name__ == "__main__":
    sys.exit(main())
