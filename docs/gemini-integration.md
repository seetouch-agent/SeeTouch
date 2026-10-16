# Gemini 集成指南

核对日期：2026-10-12；代码基线：`de755f7`。本文描述当前实现，不承诺模型价格、配额或在线可用性。

## 支持范围

CLI `python -m seetouch run` 默认选择 `GeminiReasoner`；`--reasoner doubao` 切到 Doubao。Web 调试器默认 Doubao，可用 `python -m seetouch debug --reasoner gemini` 显式选择 Gemini；Android 未安装 Gemini SDK。仅设置 `GEMINI_API_KEY` 不会切换后端。

当前使用 `google-generativeai>=0.8.0` 和 `google.generativeai.GenerativeModel`，尚未迁移到 `google-genai`。代码默认模型字符串是 `gemini-3.1-flash-lite`，可通过 `GEMINI_MODEL_ID` 覆盖；该字符串不代表本轮已验证服务可用。

## 配置与运行

```bash
python -m pip install -e .
```

在本地 `.env` 中配置：

```dotenv
GEMINI_API_KEY=replace-with-your-key
GEMINI_MODEL_ID=gemini-3.1-flash-lite
```

```bash
python -m seetouch run "打开设置" --reasoner gemini
```

key 优先读取 `GEMINI_API_KEY`，为空时回退到 `VLM_API_KEY`。这个回退只复用变量名，不会把其他厂商的 key 转换成 Gemini key。CLI 自动加载 `.env`；直接调用 Python API 时需自行加载。

## Python 接口

```python
import os
from PIL import Image
from seetouch.config_unified import load_env
from seetouch.reasoning.gemini import GeminiConfig, GeminiReasoner

load_env()
reasoner = GeminiReasoner(GeminiConfig(
    api_key=os.environ["GEMINI_API_KEY"],
    model_id=os.environ.get("GEMINI_MODEL_ID", "gemini-3.1-flash-lite"),
    history_window=8,
))
with Image.open("screenshot.png") as screenshot:
    result = reasoner.predict("打开设置", screenshot, history=[])
print(result.action)
```

`temperature`、`top_p`、`max_tokens`、`history_window` 可通过 `GeminiConfig` 构造参数设置；当前 `from_env()` 只读取 key 和模型名。`SEETOUCH_THINKING_MODE` 不控制此适配器，适配器也未提取 `reasoning_content`。这描述的是项目实现，不代表 Gemini 服务没有相关能力。

## 实际调用与错误处理

调用 `generate_content([prompt, screenshot])`，其中截图是 PIL Image；从 `usage_metadata` 提取 token 统计。

- 缺少 key：初始化失败。
- 输出无法解析：Reasoner 返回 WAIT，Runner 下一步再次预测，受重复动作和步数限制。
- API 异常：当前返回 COMPLETE，Runner 会误记为 completed。**这是待修缺陷，不是自动重试机制，也不代表任务成功。**
- 没有项目级限流队列、指数退避或多模型负载均衡。SDK 内部是否重试属于其自身行为，不能代替应用层正确处理错误。

遇到 429 或模型不可用时，检查实际项目配额、模型权限和响应；不要依据固定额度表或只看 completed 字段判断结果。

## 价格、配额和数据

旧文档中的“完全免费”、固定 RPM/RPD/TPM、固定价格和赠金均已移除。这些取决于提供商当前规则、所选模型和 API 项目；代码中的 `GEMINI_FREE_MODELS` 及日志文案仍是静态历史描述，不应当作计费依据。

- [Google AI Studio](https://aistudio.google.com/)
- [速率限制说明](https://ai.google.dev/gemini-api/docs/rate-limits)
- [计费与价格](https://ai.google.dev/gemini-api/docs/pricing)
- [SDK 文档](https://ai.google.dev/gemini-api/docs/libraries)

任务截图、指令和摘要会发送到服务商，分享 trace 或截图前需人工脱敏。

## 测试边界

```bash
python -m pytest tests/test_gemini_reasoner.py -q
```

该文件目前包含 5 项配置测试，未覆盖真实 API 请求、API 错误路径或手机闭环。仓库中不存在 `tests/test_gemini_integration.py`。完整 `tests/` 在本次核对中为 88 passed；本轮未调用真实 Gemini 服务。
