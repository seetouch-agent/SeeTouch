---
name: technical-decisions
description: 当前主分支的架构、配置、动作和错误处理边界
metadata:
  type: project
---

# 关键技术决策

更新时间：2026-10-12；核对代码：`de755f7`。旧方案的过程记录见 [开发历程](development_history.md)。

## 设备与模型边界

- `DeviceController` Protocol 位于 `seetouch/device/base.py`；PC 实现用 uiautomator2，Android 原生实现通过 DeviceBridge 调 Kotlin。
- `Reasoner.predict(instruction, screenshot, history) -> ActionOutput`，history 为 `list[StepRecord]`。不存在旧文档中的 `reason()` / `ReasoningResult` 接口。
- CLI 默认 Gemini；debug 和 Android task_entry 明确实例化 Doubao。尚无通用 OpenAI 后端入口，也无调试器自动选模型逻辑。
- 当前异常类型统一到 `core/exceptions.py`，旧模块保留导出以兼容调用。

## 配置的实际接入范围

CLI 先 `load_env()`，再用兼容 `AppSettings.from_env()`，读取设备、记录目录、最大步数和日志级别。Reasoner 自行读 key、模型等配置。已存在的环境变量优先于 `.env`。

| 配置入口 | 实际读取 |
|---|---|
| GeminiConfig.from_env | GEMINI_API_KEY / VLM_API_KEY、GEMINI_MODEL_ID |
| DoubaoConfig.from_env | VLM_API_KEY / DOUBAO_API_KEY、DOUBAO_API_URL、DOUBAO_MODEL_ID、SEETOUCH_THINKING_MODE |
| AppSettings.from_env | SEETOUCH_DEVICE_SERIAL、SEETOUCH_RUNS_DIR、SEETOUCH_MAX_STEPS、SEETOUCH_LOG_LEVEL |
| AppListJsonSource | SEETOUCH_APPLIST_PATH，缺省 ~/.seetouch/applist.json |
| Android UI | SharedPreferences 中的 key、model ID、max steps、thinking，经 JSON 传入 task_entry |

`UnifiedConfig` 不是所有入口的配置事实来源。它定义的 max_consecutive_failures、max_open_misses、settle、采样参数等环境变量未全部接入 CLI/调试器组装；要调整现有运行行为需向 Runner/Reasoner 显式传参，不能只改 `.env` 就宣称生效。

Doubao 默认 thinking=enabled，旧默认模型历史验证不支持 auto。thinking 开关由使用者决定；优化延迟不应擅自关闭。Gemini 适配器当前未接入 thinking 或 reasoning_content，不代表服务本身无推理能力。

## OPEN：显示名与本机索引

1. 尝试持久化 learned cache。
2. 对本机索引中的显示名做 casefold、去空白/分隔符后精确匹配。
3. 唯一子串候选可直接启动；其余近似候选供 VLM 重选。
4. 内部调用允许已安装包名直通，prompt 要求 VLM 输出显示名。
5. 索引存在但未命中：抛 OpenAppNotFound，Runner 写入候选反馈；默认累计 3 次后升级视觉兜底。
6. 索引缺失/为空且缓存和包名路径均失败：回桌面并抛 OpenAppNeedsVisual。

PC 索引由 helper 导出并同步；Android 通过 DeviceBridge.launchableApps 提供。索引精确同名冲突当前取第一个，不要把它描述成所有歧义均拒绝。

缓存写入的实际条件：索引启动通过 `_try_launch` 且 `entry.label != request` 时写入，所以归一化精确匹配也可能写缓存；`verify_launch=None` 时跳过前台验证。视觉兜底则在非 OPEN 动作后检测到前台不同于 baseline 时写入，并非完成整个任务后才学习。未来应加固误学边界。

旧静态表/alias 已不在 AppLauncher 路径中，`app_table.py` 文件仍保留。旧包名 fuzzy 的假阳性不能与当前显示名候选机制混为一谈。

## 动作、图像与等待

动作枚举为 CLICK/TYPE/SCROLL/OPEN/BACK/WAIT/COMPLETE。增加动作需同步 action、设备 Protocol、两个设备实现、Runner、parser、prompt 和针对性测试。

坐标为 0–1000；设备层使用真实屏幕尺寸换算。`perception/screen.py` 负责缩放和编码，不存在单独的 image.py。Runner 在源头缩至最大宽度 720，上传和截图记录共用这一图像；Doubao 编码为 PNG data URL，Gemini 将 PIL Image 交给 SDK。

成功执行后默认 settle=1.0 秒，不计入 execution_time；WAIT 默认 1.5 秒并裁剪到 0.5–5 秒，不再附加 settle。界面加载较久仍需等待，不应仅靠 prompt 禁止重复点击。

## 错误与完成语义

parser 失败抛 ParseError，由 Reasoner 回退为 WAIT。API 调用异常则在 Gemini/Doubao 中回退为 COMPLETE，这是与设计意图相反的现存缺陷；Runner 直接记 completed，不能把它当作可靠异常终止或自动重试。

Runner 默认连续执行失败 2 次、相同动作 3 次中止。OPEN 候选反馈的分支被计为 execution_success=True，表示控制流程已处理，不等于应用已打开。completed、动作执行返回和真实任务成功需区分。

## 事件和记录

EventBus 提供 screenshot_taken、reasoning_started、reasoning_done、executing 和 log。调试器分阶段显示截图、推理和执行结果；LogBridge 生命周期与任务绑定。

Doubao 从 message.reasoning_content 提取模型返回的推理字段并传给 StepResult/调试器。`trace.jsonl` 目前保存动作参数、摘要、执行标记、notes、截图路径、usage、prompt_text 与计时，未保存完整 raw_output 或 reasoning_content；不能承诺离线回放可恢复全部模型输出。

Session 目录为 `<runs_dir>/<task_id>`，总结文件名是 summary.json。记录不自动脱敏。

## Android 构建和安全边界

AGP 9.2.1、Gradle 9.4.1、Chaquopy 17.0.0、Python 3.12、minSdk 30、compileSdk 36.1、targetSdk 36。Sync 任务把根 seetouch 包复制进构建目录，保持单一源码。

takeScreenshot 提供截图、dispatchGesture 提供点击滑动、ACTION_SET_TEXT 输入，PackageManager 提供应用索引。这与“使用无障碍 UI 树作为 VLM 观察输入”不同。

任务启动先 go_home，避免模型看着 SeeTouch 自身界面持续 WAIT。无确认回调时拒绝敏感动作；UI 确认 5 分钟超时拒绝。调试器却自动批准，三种入口不可混写。

SharedPreferences key 尚未应用层加密，备份配置未排除凭据/运行记录，诊断 Activity 仍 exported。具体风险和待办见 [隐私审计](../docs/privacy-audit.md) 与 [路线图](future_roadmap.md)。
