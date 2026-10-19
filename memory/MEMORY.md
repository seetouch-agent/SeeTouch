# SeeTouch 项目记忆索引

更新时间：2026-10-19；代码核对基线：`ec78e8d`。

SeeTouch 是截图驱动的 Android GUI Agent，有 PC CLI、Web 调试器及 Kotlin/Chaquopy 独立 Android App。CLI 默认 Gemini，调试器默认 Doubao，均可选择 Gemini / Doubao / OpenAI；Android 新安装默认 OpenAI 兼容接口，保留旧豆包配置。主仓库为 [seetouch-agent/SeeTouch](https://github.com/seetouch-agent/SeeTouch)。

## 阅读顺序

1. [产品概览](product_overview.md)：当前已实现能力、入口差异和验证边界。
2. [协作约定](collaboration_style.md)：工作方式与授权边界。
3. [技术决策](technical_decisions.md)：实际接口、配置、错误路径和历史经验。
4. [路线图](future_roadmap.md)：未完成项，不能当成已有功能。
5. [开发历程](development_history.md)：按当时版本记录的里程碑；不替代当前代码。

用户操作以 [README](../README.md)、[Android 指南](../android/README.md)、[交互说明](../docs/android-interactions.md)、[OpenAI 兼容接口指南](../docs/openai-compatible.md) 和 [Gemini 指南](../docs/gemini-integration.md) 为准。隐私处理边界见 [审计记录](../docs/privacy-audit.md)。

记忆是上下文而非实时状态。历史测试数量、时延、模型能力和机器环境在复用前应核实；不得将计划、静态配置、mock 测试通过写成真机或云端服务成功。公开记忆不保存凭据、个人邮箱或个人电脑绝对路径。
