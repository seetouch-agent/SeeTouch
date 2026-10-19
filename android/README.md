# SeeTouch Android

独立 Android GUI Agent App，同时保留供 PC 导出应用索引的 helper 入口。任务在手机上执行，模型推理调用云端 Doubao 或用户选择的 OpenAI 兼容服务，不是离线模型。

核对日期：2026-10-19；对应包含 OpenAI 双协议、执行控制、追问与人工接管的工作树。

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
| App versionName / versionCode | 1.3 / 4；与 Python 包版本独立 |

PC 与 APK 的依赖安装方式不同。APK 固定 `openai==1.30.0`、`pydantic==1.10.22`、`httpx==0.27.2`，另装 Pillow 和 python-dotenv；没有安装 Gemini SDK。新安装默认使用 OpenAI 兼容接口，支持 Chat Completions 和 Responses。旧 SDK 没有 Responses resource 时，使用其认证 HTTP transport 请求 `/responses`，保留 Base URL 路径、认证及超时；安卓任务禁用自动重试，避免暂停后重发旧截图；不需要升级 APK 的 SDK。已有豆包设置继续使用原后端。

## 编译与安装

使用 Android Studio 或配置好的 JDK/Android SDK，安装匹配的 SDK Platform（36.1）。`android/local.properties` 中的 `sdk.dir` 是本机配置，不提交。Java 源兼容性 11 不等于 Gradle 运行时 JDK 要求；可使用 Android Studio 配套 JDK，并以实际 Gradle 诊断为准。

Windows PowerShell（仓库根目录）：

```powershell
cd android
.\gradlew.bat assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

macOS / Linux 对应命令为 `./gradlew assembleDebug`。首次构建需要下载依赖。APK 大小随构建配置变化。若 Windows 中文路径下的 JVM 测试报告 ClassNotFoundException，可将相同源码复制到英文路径后运行 `testDebugUnitTest assembleDebug lintDebug`，并核对源码哈希。

2026-10-19 验证：英文路径中的构建副本与工作树代码/配置哈希一致，`testDebugUnitTest` 为 **26 passed**，`assembleDebug` 成功。1.3 / versionCode 4 的 Debug APK 约 69.5 MB，包含两个 ABI；Responses Python 模块已打包，APK 签名验证通过。仓库 Python 测试在 `openai==1.30.0` 与 `1.66.0` 下各 **191 passed**；`lintDebug` 通过，0 errors / 28 warnings（版本、风格和国际化建议）。未调用真实模型服务或进行真机回归。

## 独立 App 使用

1. 安装 APK，在系统设置中启用 SeeTouch 无障碍服务。
2. 在设置页填写 API Key、Base URL 和支持图片输入的模型 ID；Key 默认隐藏，可切换显示。Base URL 保留服务商要求的路径前缀，去掉末尾的 `/chat/completions` 或 `/responses`。OpenAI 模型 ID 必填；豆包留空使用原默认模型。
3. 可点击“测试连接”，发送内置示例图和固定问题，显示响应耗时或故障分类；使用当前填写的配置，不会保存配置或截取手机屏幕。按服务商说明选择 Chat Completions 或 Responses；失败后不会自动切换协议。高级设置中可选思考强度、请求超时（5–600 秒）和最大步数（1–200）；模型默认不发送思考参数。两种后端分别保存凭据，原豆包 thinking 选择继续有效。
4. 回任务页输入指令并开始。入口先回桌面，再由前台 Service 执行；进度浮窗会出现在目标应用上方，显示当前步骤、观察/思考/执行阶段及操作摘要。拖动标题可移动，点“收起/展开”可切换大小。
5. App、浮窗和通知栏均可暂停、继续或终止。继续前重新截图；暂停期间返回的模型结果保留但不执行。登录、密码、验证码等页面会请求人工接管，也可主动点“我来操作”；完成后点继续。模型缺少信息时可追问，支持选项、文字和 App 内的系统语音回答，5 分钟未回答自动暂停。首次使用通知控制需允许通知权限。
6. 命中敏感动作规则时，浮窗会展开完整的可滚动确认信息，只有点“允许执行”后才继续；也可拒绝，5 分钟未确认默认拒绝。App 内的确认弹窗仍可使用。任务结束后浮窗显示结果，6 秒后自动关闭；完整步骤时间线保留在 App 内。

敏感操作识别依赖关键词，不能保证覆盖所有风险动作。界面显示完成也需结合实际手机状态。OpenAI 请求失败、空文本或输出不完整会中止任务并记录失败；模型输出格式解析失败先等待后重试。豆包 API 异常同样中止并记录失败。交互细节、日志及验收范围见 [Android 交互说明](../docs/android-interactions.md)。

## 执行进度浮窗

浮窗由已连接的无障碍服务管理，使用 Android 的 [TYPE_ACCESSIBILITY_OVERLAY](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_ACCESSIBILITY_OVERLAY)，不需要额外申请“显示在其他应用上层”权限。浮窗平时不抢输入焦点；追问时允许输入文字，回答后收起键盘并恢复。窗口以外的区域照常操作；无障碍服务销毁时会清理窗口和状态订阅。

Python Runner 的事件通过可选阶段回调送入 `TaskController` 的 StateFlow，App 和浮窗共用状态。步数上限是执行预算，不能当成已完成百分比，因此显示“第 N 步”和“最多 N 步”。进度回调异常不会改变执行结果。

[Android 截图 API 文档](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService#takeScreenshot(int,java.util.concurrent.Executor,android.accessibilityservice.AccessibilityService.TakeScreenshotCallback))说明，显示屏截图可能包含无障碍浮层。当前实现会在截图及点击/滑动前暂时隐藏浮窗，等待渲染帧后再执行，结束或异常后恢复显示；截图尺寸和坐标体系保持一致。相关状态及回调顺序有离线测试覆盖，浮窗显示、拖动和屏幕合成效果仍需安装 APK 后在设备上回归。

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
