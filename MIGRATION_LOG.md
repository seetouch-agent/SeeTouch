# Migration Log

Reference baseline:

- SeeTouch `52c77fb5e89861f010e39f4b0d253919bf69234f` (Apache-2.0)
- nanoMuse `b8db81c52a83551f533c5bd487d237d02cfe3cdd` (GPL-3.0-or-later, design reference only)

## M-01 — Gemini API failure must abort, not complete

- Problem: `seetouch/reasoning/gemini.py` converted every API exception into
  `Action(type=COMPLETE)`. `Runner` then marked the task completed and the CLI
  exited 0.
- Reference: SeeTouch's own Doubao/OpenAI adapters raise `VLMAPIError`; nanoMuse
  also separates a model failure from a successful tool-free answer
  (`nanomuse/agent/core.py:481`). Independent reimplementation; no code copied.
- Changes: `seetouch/reasoning/gemini.py`, `tests/test_gemini_reasoner.py`.
- Why: a failed API call must never be reported as task success.
- Proof: `test_api_failure_raises_instead_of_reporting_complete`.

## M-02 — Provider error classification and transient retries

- Problem: all provider failures became `model_error`; a single 429/500 killed
  the whole task, while authentication failures should not be retried.
- Reference: nanoMuse's explicit retryable exception set
  (`nanomuse/llm/openai_chat.py:50,68,144`). Independently implemented in
  SeeTouch's existing `VLMAPIError`/`Runner` structure.
- Changes: `seetouch/core/outcome.py`, `seetouch/core/runner.py`,
  `seetouch/cli/main.py`, `android/app/src/main/python/seetouchapp/task_entry.py`,
  `tests/unit/test_runner_resilience.py`, `tests/unit/test_responses_transport.py`.
- Policy: retry only rate-limit, server, network, and timeout classes; never
  retry 401/403 or invalid output. Default one retry, configurable with
  `SEETOUCH_MAX_MODEL_RETRIES`.
- Proof: `test_transient_api_error_retries_then_succeeds`,
  `test_auth_error_is_not_retried`.

## M-03 — Wall-clock execution budget

- Problem: `max_steps` bounded iterations but not elapsed time; a slow provider
  or device could run indefinitely.
- Reference: nanoMuse's separate wall-clock budget
  (`android/.../HandsOperator.kt:161,642`). Independent implementation.
- Changes: `Runner(task_timeout_seconds=...)`, cooperative deadline checks
  before a step and before dispatching an action; terminal reason
  `task_timeout`; CLI env `SEETOUCH_TASK_TIMEOUT`; Android config key
  `task_timeout_seconds`.
- Limitation: an in-flight network call is bounded by the provider client's
  timeout, not preempted by this deadline.
- Proof: `test_task_timeout_is_terminal_and_classified`.

## M-04 — Trace and summary identity/statistics

- Problem: trace rows had no task/model identity, and summary lacked a terminal
  reason, timestamps, and total token count.
- Reference: nanoMuse's per-task trace (`nanomuse/phone/trace.py:39-105`).
  Independently implemented on top of SeeTouch's existing `Session`.
- Changes: `seetouch/core/session.py`, `seetouch/core/runner.py`.
- New fields: `task_id`, `reasoner`, `model_id` per trace row; summary adds
  terminal reason, start/finish timestamps, and `total_tokens`.
- Proof: `test_transient_api_error_retries_then_succeeds` checks the row fields.

## M-05 — Repeatable end-to-end acceptance

- Problem: tests used mock devices; no script independently verified a real
  device after a real model run.
- Reference: nanoMuse's scripted-model/fake-device split and its on-device
  outcome checks. SeeTouch keeps its own stack and adds ADB/UIAutomator checks.
- Changes: `e2e/run_e2e.py`, `tests/unit/test_e2e_checks.py`,
  `E2E_TEST_GUIDE.md`, `E2E_TEST_REPORT.md`.
- Proof: PASS requires observed foreground package/activity, UI text, or system
  settings. A model's `COMPLETE` is recorded but never sufficient.

## M-06 — Repeat budget and visible-target rule

- Problem: the first About-phone runs needed a third scroll to reveal the target,
  but the runner aborted at 3 identical actions. The model also kept scrolling
  after the target became visible.
- Reference: nanoMuse stops an idle GUI loop later (6-step idle budget,
  `nanomuse/phone/operator.py:500,934`); this is an independently written
  threshold, not copied code.
- Changes: default `max_consecutive_identical_actions` is now 5
  (`Runner`, CLI, `UnifiedConfig`, `.env.example`); prompt rule 12 says to click
  a target as soon as it is visible and not to scroll more than twice in a row.
- Proof: the PC About-phone task passed after the change; `stuck_loop` tests and
  the remaining repeat protection are unchanged.

## Unchanged / deferred

- Existing `Runner`, `Reasoner`, `DeviceController`, PC/Android split, and
  action schema are preserved.
- Safety remains keyword-based. A policy-scope redesign was not attempted
  because it would change user-facing confirmation behavior and is not required
  to make the harness testable.
- nanoMuse GPL code was not copied, vendored, or linked.
