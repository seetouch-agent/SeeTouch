# SeeTouch Android

独立 Android GUI Agent App，同时保留供 PC 导出应用索引的 helper 入口。任务在手机上执行，模型推理调用云端 Doubao 或用户选择的 OpenAI 兼容服务，不是离线模型。

核对日期：2026-10-12；代码基线：`de755f7`。

## 架构与构建配置

Kotlin/Compose 提供 UI、前台 Service、无障碍截图/手势和 `DeviceBridge`；Chaquopy 嵌入 CPython 3.12，复用仓库根的 `seetouch/` 包。Gradle 的 `syncSeetouchPython` 任务先复制源码到构建目录，源码合并任务依赖该 Sync 任务；修改 Python 后必须重新构建并安装 APK。

| 项目 | 当前配置 |
|---|---|
| applicationId / namespace | `com.seetouch.app` |
| minSdk / targetSdk | 30（Android 11）/ 36 |
| compileSdk | 36，minor API 1 |
| AGP / Gradle wrapper | 9.2.1 / 9.4.1 |
| Chaquopy / Python | 17.0.0 / 3.12 |
| ABI | arm64-v8a、x86_64 |
| App versionName | 1.0；与 Python 包版本独立 |

PC 与 APK 的依赖安装方式不同。APK 固定 `openai==1.30.0`、`pydantic==1.10.22`、`httpx==0.27.2`，另装 Pillow 和 python-dotenv；没有安装 Gemini SDK。默认使用 Doubao，也可选 OpenAI 兼容 Chat Completions；此 SDK 不支持 Responses，PC 的 SDK 升级不应用于 APK。

## 编译与安装

使用 Android Studio 或配置好的 JDK/Android SDK，安装匹配的 SDK Platform（36.1）。`android/local.properties` 中的 `sdk.dir` 是本机配置，不提交。Java 源兼容性 11 不等于 Gradle 运行时 JDK 要求；可使用 Android Studio 配套 JDK，并以实际 Gradle 诊断为准。

Windows PowerShell（仓库根目录）：

```powershell
cd android
.\gradlew.bat assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

macOS / Linux 对应命令为 `./gradlew assembleDebug`。首次构建需要下载依赖。APK 大小随构建配置变化；本轮没有重新构建或安装。

## 独立 App 使用

1. 安装 APK，在系统设置中启用 SeeTouch 无障碍服务。
2. 在设置页选择 Doubao 或 OpenAI 兼容接口，填写对应的 key、Base URL 和模型 ID。旧配置默认继续使用 Doubao，保留原 thinking 选择；两种后端分别保存凭据。OpenAI 模型 ID 必填，思考强度留空表示模型默认，只有模型支持时才选择其他档位。
3. 回任务页输入指令并开始。入口先回桌面，再由前台 Service 执行。
4. 回到 SeeTouch 查看步骤时间线；命中敏感动作规则时在 App 内确认，5 分钟未确认默认拒绝。

敏感操作识别依赖关键词，不能保证覆盖所有风险动作。界面显示完成也需结合实际手机状态，当前 API 错误误记 COMPLETE 的问题同样影响 Android 入口。

## helper 应用索引

安装同一个 APK 后，从仓库根目录运行：

```bash
python scripts/pull_applist.py
python scripts/pull_applist.py --channel logcat
```

默认输出 `applist.json` 并同步 `~/.seetouch/applist.json`。文件通道采用 `.tmp → rename → .done`；PC 生成 request_id，只接受本次请求对应的完成标记。

Android 导出器在文件写入失败时会尝试 logcat；PC 脚本的文件通道失败不会自动解码 logcat，需要用 `--channel logcat` 重新运行。当前 logcat 协议未携带 request_id，读取已有日志时需避免并发导出和陈旧数据混淆。

logcat tag：`SEETOUCH_APPLIST`；协议：

```text
BEGIN <总块数>
CHUNK <序号>/<总块数> <base64 分块>
END <payload 字节数>
```

`schema_version=1` 的 JSON 包含生成时间、设备信息、应用 label/package/activity/version 和安装时间。它是设备清单，base64 不是加密，不应公开上传。

## OPEN 与源码入口

OPEN 使用显示名索引：学习缓存 → 归一化精确匹配 → 唯一子串匹配 → 候选反馈 → 视觉兜底。索引来自 `DeviceBridge.launchableApps()`；内部包名直通仍保留，旧 L1.5 方案已被替换。

- `app/src/main/java/com/seetouch/app/device/`：无障碍服务。
- `bridge/DeviceBridge.kt`：Python/Kotlin 接口（相对于上述 app Kotlin 包）。
- `task/`：任务状态、确认等待和前台 Service。
- `ui/`、`settings/`：Compose 界面和配置存储。
- `appindex/`、`export/`、`helper/`：应用索引及导出。
- `app/src/main/python/seetouchapp/task_entry.py`：Runner 组装和执行。
- `seetouch/device/android_native/`（仓库根）：原生设备适配器。

## 诊断与当前隐私限制

Python 自检入口：

```bash
adb shell am start -n com.seetouch.app/.diag.PythonSelfTestActivity
```

`diag.TaskRunActivity` 另有无 UI 任务入口，通过 Intent extras 接收配置，没有确认回调时拒绝敏感动作。不要把真实 key 粘贴进可保存的 shell 命令或共享日志，日常使用优先通过 App 设置输入。

当前 key 使用普通 SharedPreferences，未接入应用层加密；manifest 开启备份且 XML 未明确排除设置与任务记录。诊断和应用索引导出 Activity 仍为 exported，未通过自定义权限限制为仅 ADB 使用。这些是待加固项，并不等于已经观察到泄露。详见 [隐私审计](../docs/privacy-audit.md)。

早期模拟器闭环和本地 APK 构建记录见 [开发历程](../memory/development_history.md)；当前 Android 真机回归状态仍未在本轮核验。
