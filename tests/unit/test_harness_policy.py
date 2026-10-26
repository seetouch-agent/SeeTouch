"""循环策略：提醒 / 升级 / 终止的阶梯与优先级。"""

import pytest

from seetouch.harness.policy import LoopPolicy


def test_no_hint_when_everything_is_fine():
    policy = LoopPolicy()
    assert policy.evaluate(step=1) is None


def test_unchanged_nudge_threshold():
    policy = LoopPolicy(unchanged_nudge_at=2, unchanged_escalate_at=4)
    assert policy.evaluate(step=1, unchanged_streak=1) is None
    hint = policy.evaluate(step=2, unchanged_streak=2)
    assert hint is not None and hint.code == "unchanged_nudge"
    assert hint.action == "nudge"


def test_unchanged_escalates_before_idle_abort():
    policy = LoopPolicy(unchanged_nudge_at=2, unchanged_escalate_at=4, max_idle_steps=8)
    hint = policy.evaluate(step=5, unchanged_streak=4)
    assert hint is not None and hint.action == "escalate"
    assert "BACK" in hint.text


def test_idle_abort():
    policy = LoopPolicy(max_idle_steps=8)
    hint = policy.evaluate(step=9, unchanged_streak=8)
    assert hint is not None
    assert hint.action == "abort" and hint.terminal_reason == "idle_exhausted"


def test_repeat_nudge_and_optional_abort():
    policy = LoopPolicy(repeat_nudge_at=2, repeat_abort_at=4)
    nudge = policy.evaluate(step=2, repeated_streak=2)
    assert nudge is not None and nudge.code == "repeat_nudge" and nudge.action == "nudge"
    abort = policy.evaluate(step=4, repeated_streak=4)
    assert abort is not None and abort.action == "abort"


def test_budget_abort_wins_over_everything():
    policy = LoopPolicy(max_idle_steps=2, repeat_abort_at=2)
    hint = policy.evaluate(step=9, unchanged_streak=9, repeated_streak=9,
                           budget_reason="token_budget")
    assert hint is not None
    assert hint.action == "abort" and hint.terminal_reason == "token_budget"


def test_repeat_nudge_precedes_unchanged_nudge():
    policy = LoopPolicy(unchanged_nudge_at=2, repeat_nudge_at=2)
    hint = policy.evaluate(step=2, unchanged_streak=2, repeated_streak=2)
    assert hint is not None and hint.code == "repeat_nudge"


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        LoopPolicy(max_idle_steps=0)
    with pytest.raises(ValueError):
        LoopPolicy(unchanged_nudge_at=5, unchanged_escalate_at=2)
    with pytest.raises(ValueError):
        LoopPolicy(repeat_nudge_at=0)
