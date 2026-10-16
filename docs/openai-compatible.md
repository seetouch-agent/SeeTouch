# OpenAI 兼容 API 配置指南

CLI、Web 调试器和 Android App 共用 `OpenAIReasoner`。CLI 默认 Gemini，调试器和 Android 默认 Doubao；使用兼容接口需要显式选择后端。

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

设置页选择 OpenAI 兼容接口后填写对应的 key、Base URL 和模型 ID。各后端独立存储凭据；切换后端不会自动复制 key。旧版本豆包配置与 thinking 设置继续有效。

APK 保留 `openai==1.30.0`、`pydantic==1.10.22`、`httpx==0.27.2`，只支持 Chat Completions。未安装 Gemini SDK，不提供 Gemini 后端或 Responses 模式。

## 失败与验证边界

OpenAI 后端的 API 异常、空文本和截断输出会让 Runner 中止并记录 `completed=False`；输出格式解析失败会等待后重试。模型声明 COMPLETE 仍不代表经过独立验证的任务成功。

截图、任务和历史摘要会发送到所选服务。调试器原有的访问控制及自动批准敏感操作限制仍存在，见主 README。
