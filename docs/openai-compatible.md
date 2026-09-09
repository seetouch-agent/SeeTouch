# OpenAI 兼容 API 配置指南

SeeTouch 默认通过 OpenAI Chat Completions 协议调用多模态模型。只要服务实现兼容的
`/chat/completions` 接口并支持 `image_url` 输入，就可以通过修改配置接入。

## 配置

```ini
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL_ID=gpt-4.1-mini
```

- `OPENAI_API_KEY`：API 密钥，也可使用兼容变量 `VLM_API_KEY`
- `OPENAI_BASE_URL`：服务的 API 根地址，不要包含 `/chat/completions`
- `OPENAI_MODEL_ID`：服务提供的、支持视觉输入的模型 ID

运行：

```bash
python -m seetouch run "打开设置"
python -m seetouch run "打开设置" --reasoner openai
python -m seetouch debug --reasoner openai
```

## 思考强度

模型支持 OpenAI `reasoning_effort` 参数时，可配置：

```ini
OPENAI_REASONING_EFFORT=medium
```

可选值为 `minimal`、`low`、`medium`、`high`、`xhigh`。留空或设置为 `default`
时不发送该参数，由模型决定默认行为。不同服务和模型支持的档位可能不同；若接口返回
参数不支持错误，应留空或改用该模型支持的值。

## 编程接口

```python
from seetouch.reasoning.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleReasoner,
)

reasoner = OpenAICompatibleReasoner(
    OpenAICompatibleConfig(
        api_key="your-api-key",
        base_url="https://provider.example/v1",
        model_id="vision-model",
        reasoning_effort="medium",
    )
)
```

响应中的 `message.reasoning_content` 或 `message.reasoning` 会透传到运行记录和调试器；
token 统计同时保留 `reasoning_tokens`。

## Android App

设置页默认使用 OpenAI 兼容 API，可填写 API Key、Base URL、模型 ID，并选择模型默认
或极低、低、中、高、极高思考强度。模型不支持 `reasoning_effort` 时选择“模型默认”。
