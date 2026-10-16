---
name: future-roadmap
description: 基于当前主分支核对的待办与未实现方向
metadata:
  type: project
---

# 产品路线图

更新时间：2026-10-12；代码基线：`de755f7`。以下待办尚未因文档更新而修复。

## 已实现

- PC CLI 的 Gemini / Doubao 模型选择，默认 Gemini。
- Web 调试器单步/连续执行、事件反馈、日志与时间线（固定 Doubao）。
- Android 独立 App：Kotlin/Compose + Chaquopy，原生截图/手势、前台 Service、UI 确认。
- helper 应用索引导出与 PC 同步；显示名 OPEN、候选反馈和视觉兜底。
- BACK、WAIT、循环检测和动作后 settle。
- 仓库迁至 seetouch-agent/SeeTouch。

## 优先处理

1. **API 错误误记完成**：Reasoner 应区分异常与模型 COMPLETE，Runner 记录错误/中止；补充两个后端的失败路径测试。
2. **调试器访问和确认**：限制监听/来源、增加认证与真正的双向确认，避免自动批准敏感动作。
3. **Android 隐私**：凭据保护、备份排除、限制诊断及索引导出入口；评估日志和截图保留方式。
4. **身份信息**：公开分支的提交身份已按维护者授权统一为其 GitHub 账号及 noreply 邮箱，后续提交沿用；旧副本/缓存不随强推自动清除。本地工具 checkpoint 中凭据另行处理，不能和远程泄露混为一谈。
5. **许可证正文**：元数据声明 Apache-2.0，但当前缺少 LICENSE；由维护者确认并补齐。

## 下一轮工程工作

- 统一 CLI、debug 和 Android 的配置路径；让 UnifiedConfig 的环境变量真正接入，或减少无效配置。
- 评估 Gemini SDK 迁移、实际模型可用性和项目级限流；移除代码日志里的固定免费配额陈述。
- 补充 Gemini 真实 API 验证与 Android 真机回归；模拟器/mock 结果不能代替真机结论。
- 修复 tests 中既存的 4 项 Ruff 问题；维护测试计数的版本边界。
- doctor 支持所选后端并停止输出 key 前缀。
- helper logcat 协议加入 request_id；PC 文件失败后的回退需显式设计。
- OPEN 同名冲突、缓存验证和视觉误学边界；索引更新/失效策略。
- 运行日志脱敏、完整回放需要的字段与保留策略。

远程存在通用 OpenAI-compatible 后端开发分支，尚未合并到核对基线；先审查实现和测试，不将分支名称视为功能已完成。

## 后续产品方向

多轮澄清/ASK_USER、用户偏好、语音交互、Playbook、跨会话任务历史、多设备及 Web/桌面/iOS 设备实现。它们是计划，不是已交付能力。

当前 Android App 已存在，不再把“实现独立 App”列作长期未完成目标；后续重点是可靠性、真实设备验证和用户可用性。
