# OpenAI 兼容 API 配置指南

CLI、Web 调试器和 Android App 共用 `OpenAIReasoner`。CLI 默认 Gemini，调试器默认 Doubao；Android 新安装默认使用 OpenAI 兼容接口，已有豆包配置保留原后端。

## PC 配置

PC 依赖 `openai>=1.66.0`。更新源码后执行 `python -m pip install -e .` 同步依赖。

```dotenv
OPENAI_API_KEY=replace-with-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL_ID=replace-with-your-vision-model-id
OPENAI_API_MODE=chat_completions
OPENAI_REASONING_EFFORT=
OPENAI_TIMEOUT=60
OPENAI_MAX_RETRIES=1
```

```shell
python -m seetouch run "打开设置" --reasoner openai
python -m seetouch debug --reasoner openai
```

本后端仅读取 `OPENAI_API_KEY`，不回退使用 `VLM_API_KEY` 或豆包凭据。Base URL 不包含 `/chat/completions` 或 `/responses` 后缀。仅支持 Responses 的服务可设置 `OPENAI_API_MODE=responses`。

## 思考强度

`OPENAI_REASONING_EFFORT` 留空或填 `default` 时不发送参数。可显式填写模型支持的 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`；`none` 表示请求关闭推理，而不是使用默认值。服务端是否接受这些值取决于所选模型。

Chat Completions 通过 `reasoning_effort` 传递，Responses 通过 `reasoning.effort` 传递。豆包的 `thinking` 开关仍由豆包适配器处理，两者不互相转换。

## Android

设置页填写对应的 key、Base URL 和支持图片输入的模型 ID，并选择 Chat Completions 或 Responses；程序不会在失败后自动改用另一协议。Key 默认隐藏，模型 ID 始终显示；保存及启动前校验连接配置。高级设置提供思考强度、5–600 秒请求超时和 1–200 最大步数。各后端独立存储凭据；保存豆包不会覆盖 OpenAI 高级参数，保存 OpenAI 也不改变豆包 thinking 设置。

APK 保留 `openai==1.30.0`、`pydantic==1.10.22`、`httpx==0.27.2`，支持 Chat Completions 与 Responses。旧 SDK 没有 Responses resource 时，通过其认证 HTTP transport 请求 `/responses` 并解码输出及用量，保留自定义路径、认证、超时和重试。未安装 Gemini SDK，不提供 Gemini 后端。

Responses 输出按 [OpenAI 官方文档](https://developers.openai.com/api/docs/guides/structured-outputs) 检查完成状态；不完整响应不会作为可执行动作使用。不同服务商对图片输入、协议和思考参数的支持需分别验证，接口兼容不保证每个模型都能使用。

## 失败与验证边界

OpenAI 后端的 API 异常、空文本和截断输出会让 Runner 中止并记录 `completed=False`；输出格式解析失败会等待后重试。模型声明 COMPLETE 仍不代表经过独立验证的任务成功。

截图、任务和历史摘要会发送到所选服务。调试器原有的访问控制及自动批准敏感操作限制仍存在，见主 README。
