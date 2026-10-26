"""进度账本：容差去重、连续统计、可渲染流水。"""

from seetouch.harness.ledger import (
    ProgressLedger,
    StepEntry,
    action_digest,
    same_action,
)


def _click(step, y, outcome="ok", signature="sig-a", note=""):
    return StepEntry(
        step=step, action="CLICK", parameters={"point": [500, y]},
        outcome=outcome, screen_signature=signature, note=note,
    )


def test_same_action_tolerates_jittered_points():
    assert same_action("CLICK", {"point": [500, 290]}, "CLICK", {"point": [503, 292]})
    assert not same_action("CLICK", {"point": [500, 290]}, "CLICK", {"point": [500, 400]})


def test_same_action_separates_kinds_and_text():
    assert not same_action("CLICK", {"point": [1, 1]}, "BACK", {})
    assert not same_action("TYPE", {"text": "a"}, "TYPE", {"text": "b"})
    assert same_action("TYPE", {"text": "a"}, "TYPE", {"text": "a"})


def test_same_action_tolerance_is_configurable():
    assert not same_action("CLICK", {"point": [500, 290]}, "CLICK", {"point": [500, 310]},
                           tolerance=5)


def test_action_digest_is_stable_for_display():
    assert action_digest("CLICK", {"point": [500, 290]}) == \
        action_digest("CLICK", {"point": [500, 290]})
    assert action_digest("CLICK", {"point": [500, 290]}) != \
        action_digest("CLICK", {"point": [500, 400]})


def test_repeated_streak_counts_current_action():
    ledger = ProgressLedger()
    ledger.record(_click(1, 290))
    ledger.record(_click(2, 292))
    # 这一步如果再点同一个地方，就是连续第 3 次
    assert ledger.repeated_streak(action_type="CLICK", parameters={"point": [505, 294]}) == 3
    assert ledger.repeated_streak(action_type="CLICK", parameters={"point": [500, 800]}) == 1


def test_repeated_streak_without_current_action():
    ledger = ProgressLedger()
    ledger.record(_click(1, 290))
    ledger.record(_click(2, 292))
    assert ledger.repeated_streak() == 2


def test_repeated_streak_breaks_on_other_action():
    ledger = ProgressLedger()
    ledger.record(_click(1, 290))
    ledger.record(StepEntry(step=2, action="BACK", parameters={}))
    ledger.record(_click(3, 292))
    assert ledger.repeated_streak() == 1


def test_unchanged_streak_uses_signatures():
    ledger = ProgressLedger()
    ledger.record(_click(1, 100, signature="same"))
    ledger.record(_click(2, 200, signature="same"))
    assert ledger.unchanged_streak() == 2
    ledger.record(_click(3, 300, signature="different"))
    assert ledger.unchanged_streak() == 1


def test_unchanged_streak_ignores_missing_signature():
    ledger = ProgressLedger()
    ledger.record(_click(1, 100, signature=""))
    assert ledger.unchanged_streak() == 0


def test_consecutive_failures_and_last_success():
    ledger = ProgressLedger()
    ledger.record(_click(1, 100, outcome="ok"))
    ledger.record(_click(2, 100, outcome="failed"))
    ledger.record(_click(3, 100, outcome="failed"))
    assert ledger.consecutive_failures() == 2
    assert ledger.last_success_step == 1


def test_render_shows_outcome_and_notes():
    ledger = ProgressLedger()
    ledger.record(StepEntry(step=1, action="CLICK", summary="点设置", note="引擎未变",
                            outcome="failed"))
    text = ledger.render()
    assert "Step 1: CLICK" in text and "点设置" in text
    assert "failed" in text and "引擎未变" in text


def test_render_limits_and_empty():
    ledger = ProgressLedger()
    assert ledger.render() == ""
    for step in range(1, 6):
        ledger.record(StepEntry(step=step, action="BACK"))
    assert len(ledger.render(limit=2).splitlines()) == 2


def test_snapshot_is_json_friendly():
    ledger = ProgressLedger()
    ledger.record(_click(1, 100))
    snap = ledger.snapshot()
    assert snap["steps"] == 1 and snap["entries"][0]["action"] == "CLICK"


def test_reset_clears_entries():
    ledger = ProgressLedger()
    ledger.record(_click(1, 100))
    ledger.reset()
    assert len(ledger) == 0 and ledger.last is None


def test_long_press_jitter_is_treated_as_the_same_action():
    assert same_action(
        "LONG_PRESS", {"point": [500, 290]}, "LONG_PRESS", {"point": [503, 292]}
    )
    assert not same_action(
        "LONG_PRESS", {"point": [500, 290]}, "LONG_PRESS", {"point": [500, 400]}
    )


def test_click_and_long_press_are_different_actions():
    assert not same_action(
        "CLICK", {"point": [500, 290]}, "LONG_PRESS", {"point": [500, 290]}
    )
