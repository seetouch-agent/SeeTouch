import importlib.util
import json
from pathlib import Path


def test_replay_displays_control_times_even_without_a_captured_step(tmp_path, capsys):
    script = Path(__file__).resolve().parents[2] / "scripts/replay.py"
    spec = importlib.util.spec_from_file_location("interaction_replay", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events = [
        {"type": "takeover_start", "reason": "请登录"},
        {"type": "takeover_end"}, {"type": "paused"},
        {"type": "ASK_USER", "question": "选哪个？"},
        {"type": "user_answer", "answer": "乙"},
        {"type": "model_decision", "raw_output": "private model details"},
    ]
    (tmp_path / "interactions.jsonl").write_text("\n".join(
        json.dumps({"step": 1, "timestamp": 1000, **event}) for event in events), encoding="utf-8")
    assert module.replay(tmp_path) == 0
    output = capsys.readouterr().out
    assert "开始人工接管" in output and "结束人工接管" in output and "已暂停" in output
    assert "选哪个？" in output and "乙" in output
    assert "private model details" not in output
