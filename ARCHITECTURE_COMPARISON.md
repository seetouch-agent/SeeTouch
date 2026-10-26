# SeeTouch / nanoMuse Architecture Comparison

Baseline: SeeTouch `52c77fb5e89861f010e39f4b0d253919bf69234f` (Apache-2.0),
nanoMuse `b8db81c52a83551f533c5bd487d237d02cfe3cdd` (GPL-3.0-or-later).

This comparison is based on source inspection, not README claims. nanoMuse is a
design reference only: its GPL code is not copied into SeeTouch.

## Module Comparison

| Module | SeeTouch implementation | nanoMuse reference | Problem found | Decision | Verification |
|---|---|---|---|---|---|
| Agent loop | `seetouch/core/runner.py` `Runner.start/step/run`; per-step screenshot → reasoner → guard → action → trace | `nanomuse/agent/core.py:395-541` think/act loop, max steps, stuck nudge, wrap-up call | SeeTouch loop is sound, but task wall-clock budget is missing and model failures are single-shot | Keep SeeTouch loop; add deadline, transient-error retry, named terminal reason | `tests/unit/test_runner_resilience.py`, existing mock integration tests |
| Model adapter | `seetouch/reasoning/openai.py`, `doubao.py`, `gemini.py`; Chat Completions + Responses; usage extraction | `nanomuse/llm/openai_chat.py:50-208` retryable set, usage, prompt-tool fallback | Gemini exception silently became `COMPLETE`; errors were not split into rate-limit/server/network classes | Fix Gemini to raise `VLMAPIError`; classify retryable provider errors; retry only transient classes | Gemini regression tests, OpenAI transport tests, resilience tests |
| Model configuration | `OpenAIConfig.from_env`; Android `task_entry._create_reasoner` | Provider catalogue and per-provider adapters | Config is split between deprecated `AppSettings` and unused `UnifiedConfig`; CLI ignored protection env vars | CLI now reads the existing `SEETOUCH_*` protection env vars; no new config framework | CLI tests, E2E guide |
| Action schema | `seetouch/core/action.py`; normalized 0-1000 coordinates; `parser.py` JSON + lenient fallback | `nanomuse/phone/operator.py:53,792-1014` 999-grid and format retries | Schema is already adequate; parser falls back to `WAIT` on bad output, and existing repeat guard stops loops | Keep schema and parser; do not transplant nanoMuse's prompt dialect | `tests/unit/test_parser.py` |
| Execution state | `Runner` terminal flags; `ExecutionControl` revision checkpoints; `Session` trace/summary | `nanomuse/phone/operator.py` named outcomes; `HandsOperator.kt:147-197` independent budgets | No task deadline on PC; pause/stop is cooperative; Android has stronger control than PC | Add optional wall-clock deadline and configurable repeat/failure limits; preserve control protocol | `test_runner_resilience`, `test_execution_control` |
| Safety/permission | `seetouch/safety/guard.py` keyword pair; Android `ConfirmationGate`; sensitive-screen detector | nanoMuse sentinel policy, approval scopes, password-field rule | Keyword-only gate can miss a payment action whose summaries avoid the words. Fixing the policy is larger than this task and risks UX changes | Do not transplant GPL code or redesign safety in this iteration. Document residual risk; keep password takeover path | Existing guard and confirmation tests |
| Trace/logging | `Session` writes `step_NNN.png`, `trace.jsonl`, `interactions.jsonl`, `summary.json` | nanoMuse per-task trace and durable session repair | Trace lacked task/model identity in each row and summary | Add `task_id`, `reasoner`, `model_id`, terminal reason, start/finish timestamps, total tokens | Trace assertions in `test_runner_resilience` |
| Android runtime | Kotlin accessibility service + `DeviceBridge` + Chaquopy; `NativeAndroidController`; ADB/uiautomator2 on PC | OpenMinis accessibility + `HandsOperator`; no direct portable code | Two paths exist and must be tested separately; screenshot/reconnect behavior is device-sensitive | Keep both paths. Add independent device-state checks and separate PC/APK reports | E2E report |
| Testing | 216 Python tests, mock device integration tests; no real-model ADB suite | scripted LLM + fake phone; live smoke gated by env | Existing tests are strong offline but did not prove a real GUI loop | Add `e2e/run_e2e.py`: real ADB + real model + independent checks | E2E results and report |

## Example Trace

SeeTouch CLI path:

1. `seetouch/cli/main.py` builds `AndroidController`, `OpenAIReasoner`, `Runner`.
2. `Runner.start` creates `runs/<task_id>/` and a `Session`.
3. `Runner.step` screenshots, downscales to 720 px, calls the VLM, validates/executes one action, and appends one trace row.
4. `Session.summarize` writes `summary.json`.
5. `e2e/run_e2e.py` independently inspects foreground activity, UIAutomator text, settings, and a fresh screenshot before declaring PASS.

## What Was Not Migrated

- nanoMuse's hub/relay, channels, memory consolidation, and multi-device product surface are outside SeeTouch's GUI-agent scope.
- nanoMuse's shell/browser/MCP "ladder" is not compatible with SeeTouch's screen-only action model.
- No GPL source, prompt, or Kotlin code was copied.
