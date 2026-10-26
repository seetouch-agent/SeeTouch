"""运行预算：步数 / 时间 / token 三个维度的记账与耗尽判定。"""

from seetouch.harness.budget import RunBudget


def test_unbounded_budget_never_exhausts():
    budget = RunBudget()
    budget.start(now=0.0)
    assert budget.exhausted(10_000, now=10_000.0) is None


def test_step_budget():
    budget = RunBudget(max_steps=3)
    budget.start(now=0.0)
    assert budget.exhausted(2, now=0.0) is None
    assert budget.exhausted(4, now=0.0) == "max_steps"
    assert budget.remaining_steps(2) == 1


def test_time_budget_uses_injected_clock():
    budget = RunBudget(max_seconds=10.0, _clock=lambda: 0.0)
    budget.start()
    assert budget.exhausted(1, now=5.0) is None
    assert budget.exhausted(1, now=10.0) == "task_timeout"
    assert budget.remaining_seconds(now=4.0) == 6.0


def test_token_budget_accumulates():
    budget = RunBudget(max_tokens=100)
    budget.start(now=0.0)
    budget.consume_tokens(40)
    budget.consume_tokens(None)
    budget.consume_tokens(-5)
    assert budget.spent_tokens == 40
    assert budget.exhausted(1, now=0.0) is None
    budget.consume_tokens(70)
    assert budget.exhausted(1, now=0.0) == "token_budget"
    assert budget.remaining_tokens() == 0


def test_reset_clears_counters():
    budget = RunBudget(max_tokens=10)
    budget.start(now=0.0)
    budget.consume_tokens(10)
    budget.reset()
    assert budget.spent_tokens == 0 and budget.started_at is None
    assert budget.elapsed(now=5.0) == 0.0


def test_snapshot_reports_remaining():
    budget = RunBudget(max_steps=10, max_seconds=30.0, max_tokens=100)
    budget.start(now=0.0)
    budget.consume_tokens(30)
    snap = budget.snapshot(4, now=10.0)
    assert snap["remaining_steps"] == 6
    assert snap["remaining_seconds"] == 20.0
    assert snap["remaining_tokens"] == 70
    assert snap["spent_tokens"] == 30
