---
name: product-overview
description: SeeTouch 当前产品形态、入口差异与证据边界
metadata:
  type: project
---

# SeeTouch 产品概览

更新时间：2026-10-19；代码基线：`ec78e8d`。

## 定位

通过截图和 VLM 将自然语言任务转换为 Android 操作。产品主线为可独立在手机上运行的 App，PC 控制路径用于开发和调试；手机端执行不等于模型在手机本地推理。仓库已迁至 `seetouch-agent/SeeTouch`，对外产品名仍是 SeeTouch。

## 已有形态

| 入口 | 设备层 | 模型 | 确认方式 |
|---|---|---|---|
| CLI run | uiautomator2 | 默认 Gemini，可选 Doubao / OpenAI | 终端确认 |
| Web debug | uiautomator2 | 默认 Doubao，可选 Gemini / OpenAI | 当前自动批准，待补确认交互 |
| Android App | Accessibility + DeviceBridge | 新安装默认 OpenAI 兼容接口，保留旧豆包配置 | App / 浮窗 / 通知确认；默认 60 秒，设置可调 10–600 秒 |

Android 采用 Kotlin/Compose + Chaquopy 17.0.0 / Python 3.12，minSdk 30。构建用 Sync 任务复制根目录 Python 包，不维护第二份 Python 核心。

## 核心机制

- `Runner.start/step/run`：截图、预测、Guard、动作执行和 Session 记录；EventBus 用于调试器进度与日志。
- `DeviceController` 与 `Reasoner` Protocol：设备层和模型层解耦。
- 11 类动作：CLICK、LONG_PRESS、TYPE、SCROLL、OPEN、BACK、WAIT、COMPLETE、ASK_USER、TAKE_OVER、ANSWER。坐标 0–1000；截图宽度最多 720，保持比例。
- OPEN 使用设备显示名索引、候选反馈和视觉兜底；静态包名表已退出路径。
- 默认连续 2 次执行失败、3 次完全相同动作或达到步数上限时中止。成功设备动作后默认等待 1 秒，WAIT 不额外等待；终止与交互动作走各自处理分支。
- 记录截图、trace、交互事件和 summary；CLI/调试器保存在 runs，Android 保存在应用内部文件目录。
- Android 支持连接测试、悬浮球从当前应用发起任务、进度浮窗、暂停/继续/终止、模型追问、人工接管、敏感确认卡片、结果与答案截图来源、本地评价及可选系统语音输入/播报。
- CLI/Web 尚无追问或接管交互入口；相关模型动作会以 interaction_unavailable 中止。完整行为见 [Android 交互说明](../docs/android-interactions.md)。

## 必须保留的限制说明

Guard 是关键词启发式，不保证覆盖全部敏感动作。调试器无登录验证、监听所有网卡并自动批准确认，不能当成安全的远程执行服务。

Gemini 捕获 API 异常后仍返回 COMPLETE，可能误记 completed；OpenAI 和 Doubao 已抛出 VLMAPIError，由 Runner 中止并记录失败。模型的完成声明也没有独立结果验证。任何成功率或完成结论均需额外检查任务结果。

云端请求包含截图、任务和历史摘要，本地数据没有自动脱敏。Android key 存储、备份和 exported 诊断入口待加固。

## 当前验证

代码基线随附的 2026-10-19 验证记录：两套 SDK 环境各 201 项 Python 测试通过；Android JVM 37 项通过，APK 1.4 / versionCode 5 构建及 lint 通过。它们是既有记录，此前文档同步未重跑 suite、构建、真实模型或真机任务；详细范围见 [主 README](../README.md) 和 [Android 指南](../android/README.md)。

CLI 已有用户确认的 OpenAI 兼容 Chat Completions 真机打开应用记录；不能代替当前独立 App 回归。Responses 尚无真实服务成功验证，本轮 Android 真机验证未完成。早期试跑见 [开发历程](development_history.md)。

Android 1.4 安装包已通过 [GitHub Release](https://github.com/seetouch-agent/SeeTouch/releases/tag/v1.4) 提供；Debug 签名，Android 11+，包含 arm64-v8a / x86_64。发布批次重新构建并核验版本、签名和 Python 打包内容，未新增真机或在线模型验证，见 [Android 指南](../android/README.md)。项目使用 [Apache-2.0](../LICENSE)。
