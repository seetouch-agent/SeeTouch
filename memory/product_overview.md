---
name: product-overview
description: SeeTouch 当前产品形态、入口差异与证据边界
metadata:
  type: project
---

# SeeTouch 产品概览

更新时间：2026-10-12；代码基线：`de755f7`。

## 定位

通过截图和 VLM 将自然语言任务转换为 Android 操作。产品主线为可独立在手机上运行的 App，PC 控制路径用于开发和调试；手机端执行不等于模型在手机本地推理。仓库已迁至 `seetouch-agent/SeeTouch`，对外产品名仍是 SeeTouch。

## 已有形态

| 入口 | 设备层 | 模型 | 确认方式 |
|---|---|---|---|
| CLI run | uiautomator2 | 默认 Gemini，可选 Doubao | 终端确认 |
| Web debug | uiautomator2 | 固定 Doubao | 当前自动批准，待补确认交互 |
| Android App | Accessibility + DeviceBridge | 固定 Doubao | Compose 确认，5 分钟超时拒绝 |

Android 采用 Kotlin/Compose + Chaquopy 17.0.0 / Python 3.12，minSdk 30。构建用 Sync 任务复制根目录 Python 包，不维护第二份 Python 核心。

## 核心机制

- `Runner.start/step/run`：截图、预测、Guard、动作执行和 Session 记录；EventBus 用于调试器进度与日志。
- `DeviceController` 与 `Reasoner` Protocol：设备层和模型层解耦。
- 7 类动作：CLICK、TYPE、SCROLL、OPEN、BACK、WAIT、COMPLETE。坐标 0–1000；截图宽度最多 720，保持比例。
- OPEN 使用设备显示名索引、候选反馈和视觉兜底；静态包名表已退出路径。
- 默认连续 2 次执行失败、3 次完全相同动作或达到步数上限时中止。成功动作后默认等待 1 秒，WAIT/COMPLETE 除外。
- 记录截图、trace 和 summary；CLI/调试器保存在 runs，Android 保存在应用内部文件目录。

## 必须保留的限制说明

Guard 是关键词启发式，不保证覆盖全部敏感动作。调试器无登录验证、监听所有网卡并自动批准确认，不能当成安全的远程执行服务。

两个 Reasoner 捕获 API 异常后返回 COMPLETE，Runner 会误记 completed；模型的完成声明也没有独立结果验证。任何成功率或完成结论均需额外检查任务结果。

云端请求包含截图、任务和历史摘要，本地数据没有自动脱敏。Android key 存储、备份和 exported 诊断入口待加固。

## 当前验证

2026-10-12：`python -m pytest tests -q` 为 88 passed；`python -m ruff check seetouch` 通过。扩展到 tests/scripts 的 lint 仍有 4 项既存问题。未重跑真机、真实 API 或 APK 构建。

早期 PC 真机与 Android 模拟器结果只是历史试跑，见 [开发历程](development_history.md)。未合并远程分支的通用 OpenAI 接口不能算作当前 main 已有能力。
