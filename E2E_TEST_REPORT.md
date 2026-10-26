# End-to-End Test Report

Date: 2026-10-22/23 (Asia/Shanghai)

## Environment

| Item | Value |
|---|---|
| SeeTouch commit (baseline) | `52c77fb5e89861f010e39f4b0d253919bf69234f` |
| nanoMuse reference | `b8db81c52a83551f533c5bd487d237d02cfe3cdd` |
| Host | 32 vCPU, 62 GB RAM, RTX 5070 Ti |
| Android | API 34 `google_apis` x86_64, Pixel 5 profile, 1080x2340 |
| Emulator | Headless, KVM passed through a Docker container, SwiftShader |
| Locale | `zh-CN` |
| Model | `deepseek-flash`, OpenAI-compatible `chat_completions`, `reasoning_effort=none` |
| Android SDK | platform 34/36, build-tools 36, JDK 17/21 |

The host login user cannot access `/dev/kvm` (not in the `kvm` group), and the
pure-TCG fallback produced System UI ANRs. The final runs use `/dev/kvm` inside a
container with the host SDK/AVD mounted, so they are real Android emulator runs.

## Offline Test Baseline

```text
216 passed, 1 skipped in 24.97s
```

The one skip is the optional debugger test (`flask_socketio` not installed). A
clean `pytest` run initially failed to collect 3 files because `httpx` was
undeclared; it is now in the `dev` extra.

## PC Runner + Emulator Results

All PASS/FAIL values below come from `e2e/run_e2e.py`, which checks the device
after the agent stops. Model `COMPLETE` is recorded but not trusted.

| Task | Instruction | Result | Steps | Time | Model calls | Tokens | Independent evidence |
|---|---|---|---|---|---|---|---|
| 1 | 打开手机设置。 | PASS | 2 | 15.91 s | 2 | 5,907 | `com.android.settings/.Settings` |
| 2 | 进入设置，找到关于手机页面。 | PASS | 10 | 45.08 s | 10 | 33,281 | foreground `.SubSettings`; `MyDeviceInfoFragment` / `my_device_info_pref_screen` |
| 3 | 打开系统设置，找到蓝牙相关设置并打开蓝牙，然后返回设置首页。 | PASS | 6 | 60.25 s | 6 | 18,949 | Bluetooth `OFF -> ON`; foreground `.Settings` |

Stability repeat (`--repeat 2`, i.e. 2 additional runs per task):

| Task | Run 1 | Run 2 | Steps | Time | Tokens |
|---|---|---|---|---|---|
| open_settings | PASS | PASS | 2 / 2 | 9.09 / 8.27 s | 6,015 / 6,049 |
| about_phone | PASS | PASS | 9 / 14 | 32.61 / 50.08 s | 29,700 / 47,736 |
| bluetooth_on | PASS | PASS | 6 / 6 | 19.16 / 24.71 s | 19,016 / 18,980 |

Total: 9/9 PC E2E runs PASS.

Evidence:

- `e2e/results/20261022T153309Z/open_settings/`
- `e2e/results/20261022T155151Z/about_phone/`
- `e2e/results/20261022T155029Z/bluetooth_on/`
- `e2e/results/20261022T155328Z/report.json` (6/6 repeat report)

Each case directory contains the pre/post screenshot, UI XML, stdout/stderr,
`result.json`, and the Runner trace under `e2e/runs/<task_id>/`.

## Android APK Results

APK: `android/app/build/outputs/apk/debug/app-debug.apk` (debug, x86_64/arm64).
Accessibility enabled by ADB; task started through
`com.seetouch.app/.diag.TaskRunActivity`.

| Task | Result | Steps | Time | Tokens | Evidence |
|---|---|---|---|---|---|
| 打开手机设置。 | PASS | 2 | 23.91 s | 6,341 | foreground `com.android.settings/.Settings`; APK trace and screenshot |
| 进入设置，找到关于手机页面。 | FAIL | 25 | 322.91 s | 93,747 | `max_steps_reached`; stayed in Settings/System searches |

The APK uses the same Python Runner and the Kotlin accessibility bridge. A model
`COMPLETE` was not used as acceptance: task 1 was verified from
`dumpsys activity` and a fresh screenshot.

Evidence:

- `e2e/results/apk/taskrun.log`
- `e2e/results/apk/trace.jsonl`
- `e2e/results/apk/summary.json`
- `e2e/results/apk/final.png`
- `e2e/results/apk/foreground.txt`
- `e2e/results/apk/multistep_*` (failure evidence)

No API key is present in either log (`grep` checked against the live key).

## Failure Analysis and Changes

### F1 — Missing app index produced desktop scrolling

- Symptom: baseline run with an English emulator and no `applist.json` emitted
  three horizontal `SCROLL`s and ended `stuck_loop`.
- Cause: PC `OPEN` had no display-name index; the model did not switch to the
  app drawer.
- Fix: set the emulator locale to `zh-CN` and export the normal SeeTouch app
  index through the helper APK. This is environment setup, not a hardcoded
  task answer.
- Result: task 1 then took `OPEN 设置 -> COMPLETE`.

### F2 — 15-step budget was too small for About phone

- Symptom: first About run reached the bottom of Settings but hit
  `max_steps_reached` at 15.
- Cause: the model first tried Settings search, backed out, then scrolled.
- Fix: rerun with the documented 25-step budget (still below the product default
  of 45). No task-specific coordinate or script was added.
- Result: PASS in 10 steps.

### F3 — Independent checker false negatives

- Symptom: screenshot showed “关于模拟设备”, but the checker reported
  `about_label=False`.
- Cause: `uiautomator dump` can fail with `could not get idle state`; the old
  code then read a stale XML file. The About page is also hosted as
  `.SubSettings` with `MyDeviceInfoFragment`.
- Fix: unique dump file, require a successful dump, and accept the independent
  `dumpsys activity top` fragment markers (`MyDeviceInfoFragment`,
  `my_device_info_pref_screen`) as evidence.
- Result: the same device state now passes; the check still does not trust the
  agent's text.

### F4 — Repeat guard ended legitimate scrolling

- Symptom: the model needed a third scroll to reveal About, but SeeTouch aborted
  after 3 identical actions.
- Cause: the old limit (3) is below nanoMuse's 6-step idle budget.
- Fix: raise the default to 5 and add a generic prompt rule to click a target
  once it is visible. Existing `stuck_loop` protection remains.
- Result: PC About task passed; APK's old build was replaced with the new one.

### F5 — APK multi-step task failed

- Symptom: APK run clicked the Settings search field repeatedly; the soft
  keyboard did not appear, then it opened the System page instead of About.
- Cause: the prompt tells the model to wait for the keyboard before `TYPE`;
  on-device accessibility taps focus the field without showing the IME. Later
  taps also mapped to the wrong Settings row in the changing list.
- Status: unresolved. The PC multi-step task passes, but the on-device
  coordinate/keyboard behavior needs a focused follow-up (record focused node
  before/after tap, and allow `TYPE` when focus is proven without an IME).
- This is reported as a real failure; no success criterion was weakened and the
  APK trace is preserved.

### Environment issue — APK IPv6 timeout

- Symptom: first APK run timed out twice at 60 s, while the same call took ~4 s
  on the host.
- Cause: the emulator has no IPv6 route, but DNS returns AAAA records; the
  Android HTTP stack waited on the dead IPv6 path.
- Workaround: `echo 1 > /proc/sys/net/ipv6/conf/all/disable_ipv6` (rooted
  emulator). After that the APK task completed in 23.91 s.
- This is an emulator network limitation, not a model or Runner result.

## Reproduction

See `E2E_TEST_GUIDE.md`. The runner and checker are in `e2e/run_e2e.py`; checker
unit tests are in `tests/unit/test_e2e_checks.py`.
