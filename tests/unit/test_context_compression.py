"""上下文预算：64k 压缩、用户输入保真、确定性摘要。"""

import pytest

from seetouch.core.action import Action
from seetouch.harness.context import (
    ContextBudget,
    PinnedInputs,
    compact_history,
    estimate_tokens,
)
from seetouch.reasoning.base import StepRecord


def _record(step, *, action="CLICK", success=True, screen="设置页"):
    params = {"point": [500, 500]} if action in ("CLICK", "LONG_PRESS") else {}
    return StepRecord(
        step=step,
        action=Action(action, params),
        screen_summary=screen,
        action_summary="执行操作",
        execution_success=success,
    )


def test_estimate_tokens_counts_cjk_as_one_per_char():
    assert estimate_tokens("设置") == 2
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 0
    assert estimate_tokens("设置abcd") == 3


def test_budget_rejects_invalid_values():
    with pytest.raises(ValueError):
        ContextBudget(max_tokens=100)
    with pytest.raises(ValueError):
        ContextBudget(compress_at=0)
    with pytest.raises(ValueError):
        ContextBudget(keep_recent_steps=2, min_recent_steps=4)


def test_history_is_no_longer_capped_at_eight_steps():
    history = [_record(i) for i in range(1, 21)]
    result = compact_history(history, budget=ContextBudget(max_tokens=64000))
    assert result.kept_steps == 20
    assert not result.compressed
    assert "Step 1:" in result.text and "Step 20:" in result.text


def test_long_history_is_compressed_within_budget():
    history = [_record(i, screen="很长的界面描述" * 20) for i in range(1, 301)]
    budget = ContextBudget(max_tokens=8192, reserve_output_tokens=512)
    result = compact_history(history, budget=budget)
    assert result.compressed
    assert result.digested_steps > 0
    assert result.estimated_tokens <= budget.prompt_budget
    assert "早期步骤摘要" in result.text


def test_recent_steps_stay_verbatim_while_old_ones_are_digested():
    history = [_record(i, screen="很长的界面描述" * 10) for i in range(1, 61)]
    result = compact_history(
        history, budget=ContextBudget(max_tokens=2048, reserve_output_tokens=0)
    )
    assert "Step 50:" in result.text
    assert "Step 1:" not in result.text


def test_compaction_is_deterministic():
    history = [_record(i) for i in range(1, 61)]
    budget = ContextBudget(max_tokens=2048, reserve_output_tokens=0)
    first = compact_history(history, budget=budget)
    second = compact_history(history, budget=budget)
    assert first.text == second.text
    assert first.summary == second.summary


def test_failures_survive_in_the_digest():
    history = [_record(i, success=False, screen="很长的界面描述" * 10) for i in range(1, 61)]
    result = compact_history(
        history, budget=ContextBudget(max_tokens=2048, reserve_output_tokens=0)
    )
    assert "失败记录" in result.text


def test_action_distribution_is_reported():
    long_screen = "很长的界面描述" * 10
    history = [_record(i, action="CLICK", screen=long_screen) for i in range(1, 21)]
    history += [_record(i, action="BACK", screen=long_screen) for i in range(21, 31)]
    history += [_record(i, screen=long_screen) for i in range(31, 46)]
    result = compact_history(
        history, budget=ContextBudget(max_tokens=2048, reserve_output_tokens=0)
    )
    assert "动作分布" in result.text


def test_empty_history_renders_placeholder():
    result = compact_history([], budget=ContextBudget())
    assert result.text == "无"
    assert result.estimated_tokens == 0


def test_pinned_inputs_are_kept_and_deduplicated():
    pinned = PinnedInputs()
    assert pinned.add("问题：选哪个\n回答：第二个")
    assert not pinned.add("问题：选哪个\n回答：第二个")
    assert pinned.add("问题：继续吗\n回答：继续")
    assert len(pinned) == 2
    text = pinned.render()
    assert text.count("回答：第二个") == 1
    assert "继续" in text
    assert "必须遵守" in text


def test_pinned_inputs_are_ignored_when_empty():
    pinned = PinnedInputs()
    pinned.add("   ")
    assert len(pinned) == 0
    assert pinned.render() == ""
    pinned.add("问题：A\n回答：B")
    pinned.clear()
    assert pinned.render() == ""


def test_pinned_text_is_reserved_from_history_budget():
    history = [_record(i, screen="描述" * 50) for i in range(1, 200)]
    budget = ContextBudget(max_tokens=4096, reserve_output_tokens=0)
    plain = compact_history(history, budget=budget)
    with_pinned = compact_history(
        history, budget=budget, pinned_text="问题：X\n回答：Y" * 200
    )
    assert with_pinned.estimated_tokens <= plain.estimated_tokens + 1
