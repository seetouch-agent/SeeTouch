---
name: future-roadmap
description: 基于当前主分支核对的待办与未实现方向
metadata:
  type: project
---

# 产品路线图

更新时间：2026-10-19；代码基线：`ec78e8d`。区分已实现功能、验证缺口和未来计划。

## 已实现

- PC CLI 的 Gemini / Doubao / OpenAI 模型选择，默认 Gemini；OpenAI 支持两种协议。
- Web 调试器单步/连续执行、事件反馈、日志与时间线（默认 Doubao，可选 Gemini / OpenAI）。
- Android 独立 App：Kotlin/Compose + Chaquopy，原生截图/手势、前台 Service；新安装默认 OpenAI 兼容接口，保留豆包设置。
- Android 连接测试、悬浮球、进度浮窗、暂停/继续/终止、ASK_USER 追问、人工接管、敏感确认卡片与通知控制。
- 结构化 ANSWER、答案截图来源、持久化结果卡片、结束通知、本地评价、系统语音输入及可选 TTS；完整行为见 [交互说明](../docs/android-interactions.md)。
- helper 应用索引导出与 PC 同步；显示名 OPEN、候选反馈和视觉兜底。
- BACK、WAIT、循环检测和动作后 settle。
- 仓库迁至 seetouch-agent/SeeTouch。

## 优先处理

1. **Gemini API 错误误记完成**：修复 Gemini 异常返回 COMPLETE 的路径；OpenAI/Doubao 已改为 VLMAPIError 中止，后续保留回归。
2. **调试器访问和确认**：限制监听/来源、增加认证与真正的双向确认，避免自动批准敏感动作。
3. **Android 隐私**：凭据保护、备份排除、限制诊断及索引导出入口；评估日志和截图保留方式。
4. **交付与验收**：当前无 GitHub Release / APK 下载资产；完成 Android 真机回归后准备可复现的发布版本、安装包与演示材料。已按元数据声明补齐 [Apache-2.0 正文](../LICENSE)。

## 下一轮工程工作

- 统一 CLI、debug 和 Android 的配置路径；让 UnifiedConfig 的环境变量真正接入，或减少无效配置。
- 评估 Gemini SDK 迁移、实际模型可用性和项目级限流；移除代码日志里的固定免费配额陈述。
- 补充 Gemini 真实 API 验证与 Android 真机回归；模拟器/mock 结果不能代替真机结论。
- 验证记录集中维护于 README / Android 指南；10月12日扩展 lint 的4项问题属于旧快照，复用前重新检查。
- doctor 支持所选后端并停止输出 key 前缀。
- helper logcat 协议加入 request_id；PC 文件失败后的回退需显式设计。
- OPEN 同名冲突、缓存验证和视觉误学边界；索引更新/失效策略。
- 运行日志脱敏、完整回放需要的字段与保留策略。

OpenAI 兼容后端已进入 main；接口与 mock HTTP 测试不代表每个第三方服务或模型均已在线验证。Responses 尚无真实服务成功验证记录。

## 后续产品方向

用户偏好、Playbook、完整的跨会话任务历史管理、多设备及 Web/桌面/iOS 设备实现仍为计划。Android 已有 ASK_USER、系统语音输入和 TTS；持续语音对话及 CLI/Web 追问/接管交互尚未提供。

当前 Android App 已存在，不再把“实现独立 App”列作长期未完成目标；后续重点是可靠性、真实设备验证和用户可用性。
