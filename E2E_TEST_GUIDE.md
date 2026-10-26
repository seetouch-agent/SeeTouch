# End-to-End Test Guide

This guide reproduces the real Android + real VLM run. Mock tests are separate
and never count as E2E.

## 1. Python baseline

```bash
cd SeeTouch
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m pytest -q
```

Expected baseline: 216 passed, 1 skipped (the skipped test needs the optional
`debugger` extra). `httpx` is declared in the `dev` extra because the test suite
imports it directly.

## 2. Android SDK and emulator

Required: JDK 17 and 21, Android SDK platform 34/36, build-tools 36, platform-tools,
emulator, `system-images;android-34;google_apis;x86_64`.

Create the AVD once:

```bash
export ANDROID_HOME=/path/to/android-sdk
export ANDROID_AVD_HOME=/path/to/avd
echo no | "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd \
  -n seetouch_api34 -k 'system-images;android-34;google_apis;x86_64' \
  --device pixel_5 --force
```

The test host used here does not grant the login user access to `/dev/kvm`, but
Docker can pass it through. This keeps hardware acceleration and is still a real
Android emulator:

```bash
docker run -d --name seetouch-emulator --network host --device /dev/kvm \
  -v /usr:/usr:ro -v /lib:/lib:ro -v /lib64:/lib64:ro \
  -v /bin:/bin:ro -v /sbin:/sbin:ro -v /etc:/etc:ro \
  -v "$ANDROID_HOME":"$ANDROID_HOME":ro \
  -v "$ANDROID_AVD_HOME":"$ANDROID_AVD_HOME" \
  -v "$HOME/.android:/root/.android" \
  -e ANDROID_SDK_ROOT="$ANDROID_HOME" -e ANDROID_HOME="$ANDROID_HOME" \
  -e ANDROID_AVD_HOME="$ANDROID_AVD_HOME" \
  ubuntu:24.04 "$ANDROID_HOME/emulator/emulator" \
  -avd seetouch_api34 -no-window -no-audio -no-boot-anim \
  -gpu swiftshader_indirect -no-snapshot -wipe-data \
  -memory 3072 -cores 8 -port 5554
```

Wait for `adb shell getprop sys.boot_completed` to return `1`.

For a Chinese task on an English image, set the emulator locale to `zh-CN` and
reboot. Then refresh the app index:

```bash
adb shell am start -n com.seetouch.app/.helper.AppListExportActivity
python scripts/pull_applist.py --serial emulator-5554
```

The index lets `OPEN 设置` resolve to `com.android.settings`. This is normal
SeeTouch setup, not a hardcoded action.

## 3. Model configuration

```bash
cp .env.e2e.example .env.e2e
chmod 600 .env.e2e
# fill OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL_ID
```

`.env.e2e` is ignored by git. `OPENAI_REASONING_EFFORT=none` is required for
`deepseek-flash`: otherwise its reasoning text can consume the output budget and
leave `content` empty.

## 4. Run the PC Runner suite

```bash
export PATH="$ANDROID_HOME/platform-tools:$PATH"
source .venv/bin/activate
unset ALL_PROXY all_proxy       # httpx has no SOCKS support by default
python e2e/run_e2e.py --max-steps 25
```

Repeat for stability:

```bash
python e2e/run_e2e.py --max-steps 25 --repeat 2
```

Each case gets its own directory under `e2e/results/<UTC timestamp>/`:

- `before/screenshot.png`, `before/ui.xml`
- `agent.stdout.log`, `agent.stderr.log`
- `after/screenshot.png`, `after/ui.xml`
- `result.json` with PASS/FAIL, steps, tokens, timings, and every action

`e2e/run_e2e.py` decides PASS from ADB state: foreground package/activity,
UIAutomator text, and Android settings. A model `COMPLETE` is recorded but never
sufficient.

## 5. Run the APK path

Build and install:

```bash
cd android
JAVA_HOME=/path/to/jdk21 ./gradlew --no-daemon assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Enable the accessibility service:

```bash
adb shell settings put secure enabled_accessibility_services \
  com.seetouch.app/com.seetouch.app.device.SeeTouchAccessibilityService
adb shell settings put secure accessibility_enabled 1
```

On this emulator IPv6 has no route while DNS returns AAAA records. Disable IPv6
before the APK run, otherwise the HTTP client waits for a 60-second timeout:

```bash
adb root
adb shell 'echo 1 > /proc/sys/net/ipv6/conf/all/disable_ipv6'
```

Run the no-UI diagnostic entry:

```bash
adb logcat -c
adb shell am start -n com.seetouch.app/.diag.TaskRunActivity \
  --es instruction '打开手机设置。' \
  --es api_key "$OPENAI_API_KEY" \
  --es reasoner openai \
  --es base_url "$OPENAI_BASE_URL" \
  --es model_id "$OPENAI_MODEL_ID" \
  --es reasoning_effort none --ei max_steps 15
adb logcat -s SEETOUCH_RUN:I
```

Verify independently:

```bash
adb shell dumpsys activity activities | grep topResumedActivity
adb exec-out screencap -p > /tmp/apk-final.png
```

The APK writes its trace under
`/data/user/0/com.seetouch.app/files/runs/<task_id>/`; with a debug build:

```bash
adb exec-out run-as com.seetouch.app cat files/runs/<task_id>/trace.jsonl
```

## 6. Interpreting failures

- No `content`/`finish_reason=length`: lower reasoning or raise output budget;
  do not mark the task complete.
- `task_timeout` / `timeout`: check provider reachability and the configured
  request timeout before changing task logic.
- `stuck_loop`: inspect the last screenshot and repeat count. Repeated scrolling
  over a list is expected; repeated clicks with no UI change is not.
- Independent checker FAIL while the screenshot looks correct: verify UIAutomator
  freshness and the activity/fragment, then fix the checker, not the verdict.
