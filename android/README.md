# SeeTouch Android

SeeTouch 的 Android 端工程：**独立不依赖电脑的 on-device GUI Agent 主 App**，同时保留 helper APK 能力（连接电脑时可导出应用索引）。

架构为 Chaquopy 混合方案：CPython 3.12 嵌入 APK，`seetouch/` Python 包（core/reasoning/perception/safety）原封不动跑在手机上；仅设备交互层（无障碍服务手势/截图）与 UI（Compose）用 Kotlin。Gradle sourceSet 直接指向仓库根的 `seetouch/`，PC 端 Python 代码更新后**重新构建 APK 即同步，零移植**。

## 模块结构

```
app/src/main/java/com/seetouch/app/
├── SeeTouchApplication.kt   # Python 运行时初始化 + DeviceBridge 注入
├── ui/          # Compose UI（任务页/实时时间线/敏感动作确认弹窗/设置页）
├── task/        # 任务状态机
│   ├── TaskState.kt             # TaskStatus / StepInfo / TaskUiState
│   ├── TaskController.kt        # 单例 StateFlow,Python 回调 → UI 状态
│   └── TaskExecutionService.kt  # 前台 Service,承载任务线程
├── settings/    # AppSettings(API key/Base URL/模型/最大步数/思考强度)
├── device/      # SeeTouchAccessibilityService(手势注入/截图/前台包名)
├── bridge/      # DeviceBridge:Python↔Kotlin 唯一门面
├── appindex/    # 应用索引领域层(helper 与主 App 共用;OPEN L1.5 复用)
├── export/      # helper 导出通道(文件 + logcat 兜底)
├── helper/      # ADB 桥接壳(helper 模式入口)
└── diag/        # 诊断入口(Python 自检 / 无 UI 任务执行)

app/src/main/python/seetouchapp/
├── task_entry.py   # run_task():Kotlin → Runner 的任务入口
└── selftest.py     # 设备上 Python 环境自检
```

## 本地编译

前置：Android Studio（或命令行 SDK），SDK Platform 36 + Build-Tools；首次构建会自动下载 Chaquopy 的 Python 3.12 运行时和 pip 依赖（openai/pydantic/httpx/pillow），需联网，耗时较长。

```bash
cd android
./gradlew assembleDebug
# 产物: app/build/outputs/apk/debug/app-debug.apk (~65MB,含 CPython)
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

也可直接用 Android Studio 打开 `android/` 文件夹点 Run。

## 用法一：独立 App（不依赖电脑）

1. 安装 APK 后，在系统设置 → 无障碍 中开启「SeeTouch」服务（App 内有跳转按钮）
2. 打开 SeeTouch → 右上角齿轮进设置页，填写 OpenAI 兼容 API Key、Base URL、模型 ID，
   按模型能力选择思考强度（不支持 `reasoning_effort` 时选“模型默认”），保存
3. 回任务页输入自然语言指令（如「打开设置」「在哔哩哔哩搜索采莲曲」）→ 点「开始执行」
4. App 自动回桌面开始执行；执行由前台 Service 承载，通知栏可见。回到 SeeTouch 可看实时步骤时间线；遇敏感动作（支付/删除等）会弹确认框，5 分钟未确认默认拒绝

## 用法二：helper 模式（连接电脑导出应用索引）

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk

# 一键触发 + 拉取 + 校验（仓库根目录）
python scripts/pull_applist.py

# 或手动操作
adb shell am start -n com.seetouch.app/.helper.AppListExportActivity
adb pull /sdcard/Android/data/com.seetouch.app/files/applist.json
```

## 导出协议（helper）

### 文件通道（默认）

写入 `getExternalFilesDir()/applist.json`：先写 `.tmp` → 原子 rename → 写 `applist.json.done` 状态标记。PC 端轮询 `.done` 出现后再 pull，避免读到半截文件。

### logcat 兜底通道

`adb pull` 不可用时使用，tag 为 `SEETOUCH_APPLIST`，行协议：

```
BEGIN <总块数>
CHUNK <序号>/<总块数> <base64 分块>
END <payload 字节数>
```

触发方式：`adb shell am start -n com.seetouch.app/.helper.AppListExportActivity --es channels logcat`（文件通道失败时也会自动兜底）。

### JSON 格式（schema_version = 1）

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-05T12:00:00Z",
  "device": {"sdk_int": 34, "manufacturer": "Xiaomi", "model": "...", "locale": "zh-CN"},
  "count": 447,
  "apps": [
    {
      "label": "抖音",
      "package": "com.ss.android.ugc.aweme",
      "activity": "com.ss.android.ugc.aweme.splash.SplashActivity",
      "version_name": "28.0.0",
      "version_code": 280000,
      "system": false,
      "first_install_time": 0,
      "last_update_time": 0
    }
  ]
}
```

字段变更时递增 `schema_version`，不要原地改语义。

## OPEN 策略（on-device）

App 内 OPEN 以**应用名**为一等公民（VLM 只输出桌面显示名，不输出包名）：learned cache → 索引精确匹配 → 唯一强模糊命中直接启动 → 歧义时把相似候选反馈给 VLM 重选 → 视觉兜底。索引数据源为 `DeviceBridge.launchableApps()`（PackageManager 枚举，复用 appindex/）。详见 `seetouch/device/android/app_launcher.py` 与 `app_index.py`。

## 诊断入口（ADB）

```bash
# Python 环境自检
adb shell am start -n com.seetouch.app/.diag.PythonSelfTestActivity
# 无 UI 任务执行(logcat tag SEETOUCH_RUN)
adb shell am start -n com.seetouch.app/.diag.TaskRunActivity \
    --es instruction "打开设置" \
    --es api_key "<API_KEY>" \
    --es base_url "https://api.openai.com/v1" \
    --es model_id "gpt-4.1-mini"
```
