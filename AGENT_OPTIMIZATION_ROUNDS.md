# Agent Optimization Rounds

This is the second optimization pass, driven by more complex multi-step tasks.
nanoMuse is GPL-3.0-or-later and SeeTouch is Apache-2.0: only design ideas were
reimplemented, no source was copied.

## Baseline

Complex task suite on the PC Runner + Android 34 emulator, before this pass:

| Task | Result | Steps |
|---|---|---|
| 开启深色主题并返回设置首页 | PASS | 6 |
| 关闭自动设置时间并返回设置首页 | PASS | 10 |
| 打开 Chrome 的应用信息页面 | FAIL | 9, stopped in Settings search |

Evidence: `e2e/results/20261022T162716Z/`.

The APK multi-step baseline was worse: `进入设置，找到关于手机页面。` failed at
25/25 steps, 322.9 s, 93,747 tokens.

## R1 — UI-tree observation on the PC path

- Failure: the model only saw pixels. In the Chrome task it used search, landed
  in Settings SPA, and could not tell that the result page was already Chrome's
  app-info page.
- Reference: nanoMuse appends a node list to the image input
  (`nanomuse/phone/operator.py:308-314,1014-1016`). Independent implementation.
- Change: `AndroidController.ui_context()` parses `uiautomator2.dump_hierarchy`,
  emits text/desc/id/class/clickable/scroll/edit/focus plus normalized center,
  skips SystemUI, caps 90 nodes / 6000 chars. `Runner` appends it to the
  instruction and records it in `trace.jsonl`.
- Tests: `tests/unit/test_ui_context.py`.
- Result: the same Chrome task completes in 7 steps and the screenshot shows the
  real Chrome app-info page.

## R2 — No-change feedback

- Failure: repeated taps can leave the screen unchanged while the model receives
  no explicit feedback, so it retries the same action.
- Reference: nanoMuse's idle/repeat note after identical actions
  (`nanomuse/phone/operator.py:498-500,921-937`). Independent implementation.
- Change: `Runner` hashes the UI tree (or a cropped screenshot when no tree) and
  injects “界面与之前 N 步相同 / 上一步是 X” from streak 2. The streak is stored
  in the trace and appended to step notes.
- Tests: `test_runner_flags_unchanged_screen_on_next_step`.
- Result: deterministic feedback path; no task-specific keyword or coordinate.

## R3 — Android accessibility-tree grounding + focus semantics

- Failure: APK runs had no UI tree, so ±2 px taps hit the wrong Settings row and
  `TYPE` waited forever for a soft keyboard that accessibility input does not
  need.
- Reference: the same node-list idea (`operator.py:308-314`) and Android
  accessibility focus/edit semantics; independent Kotlin/Python implementation.
- Change:
  - `SeeTouchAccessibilityService.uiNodes()` walks the active window (text,
    description, id, class, bounds, click/scroll/edit/focus), skipping SystemUI
    and SeeTouch's own overlays.
  - `DeviceBridge.uiNodes()` and `NativeAndroidController.ui_context()` format
    the same 0-1000 centers as the PC path.
  - Prompt rule 6 now allows `TYPE` when the tree shows `edit,focus`, even without
    an IME.
- Tests: `test_native_controller_formats_bridge_nodes`; `assembleDebug` +
  `testDebugUnitTest`.
- Result: the exact APK multi-step task went from **25 steps / 322.9 s / 93,747
  tokens FAIL** to **14 steps / 202.2 s / 63,253 tokens PASS**, with five
  independent `MyDeviceInfo` markers. Evidence: `e2e/results/apk_r3/`.

## R4 — Jitter-tolerant repeat guard

- Failure: the old identity check used exact JSON. Clicks at `[500,290]`,
  `[500,292]`, `[500,289]` counted as three different actions, bypassing
  `stuck_loop`.
- Reference: nanoMuse's pixel-tolerant same-tap threshold
  (`nanomuse/phone/operator.py:492-493,523`) and 6-step idle budget.
- Change: CLICK/SCROLL coordinates are quantized to 2% (20/1000) only for the
  repeat identity check; the action itself still uses the original coordinates.
  The 5-action limit is unchanged.
- Tests: `test_jittered_clicks_count_as_identical`.
- Result: the old 10-tap APK failure pattern now collapses into a diagnosable
  repeat sequence instead of burning the full budget.

## R5 — Parse-failure feedback and progress budget

- Failure: malformed model output became a silent `WAIT`; the rejected output was
  never shown to the model and long tasks had no explicit remaining-budget line.
- Reference: nanoMuse's format retry loop with the rejected reply echoed back
  (`nanomuse/phone/operator.py:715,1023-1036`). Independent implementation.
- Change: `ActionOutput.parse_error` is set by OpenAI/Doubao/Gemini adapters.
  `Session` adds the first 160 characters plus “只输出一个 JSON 对象” to the next
  history. `Runner` adds “已完成 N 步 / 剩余最多 M 步” every step.
- Tests: `test_parse_error_feedback_enters_history`, progress assertion in the
  no-change test.
- Result: format drift becomes visible and recoverable instead of silent waiting.

## R6 — Reject premature completion

- Failure found in the final complex regression: after `OPEN 设置`, the model
  returned `COMPLETE` for a three-clause task; SeeTouch recorded a false success
  and dark mode was still off.
- Reference: nanoMuse keeps an explicit outcome status separate from model text
  (`nanomuse/phone/operator.py:317-330`); SeeTouch now applies the same principle
  to completion claims.
- Change: for instructions with multiple action clauses, a successful `COMPLETE`
  is rejected until at least one meaningful action (CLICK/LONG_PRESS/TYPE/SCROLL/BACK) has
  executed. One rejection is fed back; a second rejection aborts with
  `premature_completion` rather than reporting success.
- Tests: `test_multi_step_task_rejects_completion_right_after_open`,
  `test_single_step_task_accepts_completion_after_open`.
- Result: the dark-theme task now continues and passes (6 steps) instead of
  falsely completing in 2 steps.

## R7 — Harness 分层：观测 / 落点校准 / 账本 / 策略

- Failure: the loop treated observation, change detection, coordinates and budgeting as
  three unrelated values inside `_step_once`. A click that missed by a few dozen units
  looked the same as a model ignoring feedback, and R4's bucket quantisation mis-judged
  points that straddled a bucket boundary (299 vs 301 → different buckets).
- Reference: nanoMuse's harness layering (image first, node table as an aid; tolerant
  same-tap check; explicit idle budget; failure text fed back into the next prompt).
  Independent implementation — no source copied (GPL-3.0 vs Apache-2.0).
- Change:
  - `seetouch/harness/` adds `nodes`, `observation`, `protocol`, `ledger`, `budget` and
    `policy`: one structured observation per step, reused by prompt / trace / grounding.
  - Both device controllers expose `ui_elements()`; `ui_context()` becomes a thin render
    over it, so a frame is dumped once.
  - `ground_action()` snaps a `CLICK` to the nearest actionable node centre within 60
    normalised units and records `click_grounded` in the trace;
    `SEETOUCH_CLICK_GROUNDING=0` disables it.
  - `same_action()` replaces R4's bucketing with a distance comparison, and
    `Session.consecutive_identical_actions()` now shares it.
  - `LoopPolicy` adds the missing middle tier: nudge (2) → escalate (4) → abort
    `idle_exhausted` (8), plus a `RunBudget` for steps / wall clock / tokens.
- Tests: `tests/unit/test_harness_*.py` and `tests/unit/test_runner_grounding.py`
  (59 new tests); full suite 284 passed / 1 skipped.
- Result: **not yet benchmarked on a device.** Behaviour defaults match the pre-R7 loop
  (same nudge threshold and wording, idle budget placed after the existing
  5-identical-action guard), so task outcomes should not shift until a device run with
  grounding enabled vs disabled is compared. See `docs/harness-design.md`.

## Final Complex-Suite Result

Final code, same three tasks:

| Task | Result | Steps | Time | Tokens |
|---|---|---|---|---|
| 开启深色主题并返回设置首页 | PASS | 6 | 21.6 s | 25,397 |
| 关闭自动设置时间并返回设置首页 | PASS | 11 | 39.3 s | 50,711 |
| 打开 Chrome 的应用信息页面 | PASS | 7 | 23.7 s | 32,330 |

3/3 PASS. Evidence: `e2e/results/20261022T165449Z/`.

The APK keeps a passing 14-step multi-step record (`e2e/results/apk_r3/`). A
later APK rerun stopped at step 9 with `user_stopped` because the no-UI
`TaskRunActivity` exposes no interaction callback and the sensitive-screen gate
correctly refused to continue; evidence is in `e2e/results/apk_final_stop/`.
This is a diagnostic-entry limitation, not a model success.

## What Was Not Changed

- `ExecutionControl` revision/checkpoint semantics.
- Safety confirmation keywords and the Android `ConfirmationGate`.
- 0-1000 normalized coordinate contract and 720px working screenshot.
- The independent E2E checker was not weakened; the Chrome app-info check was
  corrected to recognize both `AppInfoDashboardActivity` and the SPA-hosted
  app-info page by its actual controls.

## Cross-project corroboration

A separate source audit pinned these MIT/Apache-2.0 projects (clones outside the
working tree):

| Project | Commit | License | Matched mechanism |
|---|---|---|---|
| `google-research/android_world` | `f8e78c0ab0bb` | Apache-2.0 | element extraction / stable-state polling / closed `JSONAction` vocabulary (`android_world/env/representation_utils.py:136`, `interface.py:243`, `json_action.py:38`) |
| `droidrun/droidrun` | `301856138c6e` | MIT | occlusion-aware tap points, malformed-call limit, focus-then-type (`mobilerun/tools/ui/state.py:72,113`, `geometry.py:13,43`, `agent/fast_agent/fast_agent.py:63-91`, `agent/utils/actions.py:396`) |
| `X-PLUG/MobileAgent` | `11cea575561f` | MIT | A/B/C action reflection and keyboard pre/post state (`Mobile-Agent-E/MobileAgentE/agents.py:570,643`, `inference_agent_E.py:706`) |
| `TencentQQGYLab/AppAgent` | `2c1900422caf` | MIT | flat indexed elements, dedup by center distance, grid fallback (`scripts/and_controller.py:56`, `scripts/task_executor.py:257`) |
| `openatx/uiautomator2` | `bad641e7a861` | MIT | focus/IME-aware Unicode input (`uiautomator2/_input.py:49,107,123`) |
| `lgy0404/MemGUI-Bench` | `3fb01b6cc0d1` | MIT | model-driven history folding and memory CRUD (`src/mobile_world/agents/implementations/memgui_agent.py:65,323`) |

The implemented rounds align with these mechanisms:

- R1/R3 use the same accessibility-element idea as AndroidWorld/AppAgent; our
  implementation is independent Python/Kotlin on SeeTouch's device API.
- R2's no-change streak is the free, hash-based subset of Mobile-Agent-E's
  A/B/C reflection; we deliberately avoid an extra VLM call per step.
- R4's 2% coordinate quantization is the same class of fix as droidrun's
  pixel-tolerant tap and valid-index errors.
- R5's parse feedback matches droidrun's named malformed-call handling, but
  SeeTouch currently feeds the rejected output back once rather than adding a
  full 3-attempt inner loop.
- R6's explicit terminal status is the same separation of model text and
  harness outcome seen in nanoMuse's `Outcome`.

### Deliberately deferred

- **Post-action stable-state polling** (AndroidWorld `_get_stable_state`): high
  value, but it changes action latency and needs a separate flake benchmark.
- **A dedicated companion IME** (uiautomator2): robust for Chinese/Unicode, but
  changing the user's default IME is an invasive product decision.
- **Four-agent decomposition / per-step reflection VLM** (Mobile-Agent-E): cost
  and latency are too high for SeeTouch's loop.
- **Model-driven history folding** (MemGUI): promising for tasks beyond ~30
  steps, but it changes the action protocol and needs its own regression suite.

## R8 — 上下文成本：前缀缓存 / 64k 压缩 / 用户输入保真

- Failure: every step rebuilt one prompt string with the task at the top, so no prefix was
  ever stable across steps and provider prefix caching could never hit. History was capped
  at 8 steps regardless of how much context the model could take, and ASK_USER answers
  lived only inside the current instruction, where a long task could push them out.
- Reference: the context handling typical of Codex/Hermes-style agents (stable prefix,
  budget-driven compaction, user instructions pinned). Independent implementation.
- Change:
  - `SYSTEM_PROMPT_STATIC` split out of the template; adapters send it as `messages[0]`,
    with task/history/observation in `messages[1]`.
  - `harness/context.py`: token estimator, `ContextBudget` (64k, 2k output reserve, 60%
    trigger), deterministic `compact_history` (recent 12 verbatim, older digested into
    action distribution / screens / failures), `PinnedInputs` for user answers.
  - `usage.cached_tokens` recorded and accumulated into `RunResult.total_cached_tokens`.
  - Screenshots default to JPEG q=85; thinking defaults to `disabled`.
- Tests: `tests/unit/test_context_compression.py`, `test_prefix_cache.py`,
  `test_runner_pinned_inputs.py`, `test_screen_encoding.py` (28 cases);
  full suite 326 passed / 1 skipped.
- Result: **not yet measured on device.** The expected effect is a lower per-step token
  bill (cache hits + JPEG) and no loss of user instructions in long tasks; both need an
  A/B E2E run before being quoted as numbers.
