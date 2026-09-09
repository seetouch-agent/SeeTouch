# Gemini API 集成指南

本文档介绍如何在 SeeTouch 项目中使用 Google Gemini 免费 API。

## 概述

SeeTouch 可选使用 Google Gemini API，Gemini 后端默认模型为
**Gemini 3.1 Flash-Lite**。

**为什么选择 Gemini？**
- ✅ 完全免费，无需信用卡
- ✅ 支持多模态（文本 + 图像）
- ✅ 高频调用限制（15 RPM / 500 RPD）
- ✅ 低延迟，适合实时 GUI 交互

## 免费模型对比

| 模型 | RPM | RPD | 特点 |
|------|-----|-----|------|
| **gemini-3.1-flash-lite** (默认) | 15 | 500 | 最高频率，最低延迟 |
| gemini-2.5-flash | 10 | 250 | 平衡性能与速度 |
| gemini-2.5-pro | 5 | 100 | 更强推理能力 |

- **RPM**: Requests Per Minute（每分钟请求数）
- **RPD**: Requests Per Day（每天请求数）
- 所有模型共享 **250,000 TPM**（每分钟 token 数）
- 支持 **100 万 token 上下文窗口**

参考：[官方速率限制文档](https://ai.google.dev/gemini-api/docs/rate-limits)

## 快速开始

### 1. 获取 API Key

前往 [Google AI Studio](https://aistudio.google.com)，点击左下角 **"Get API Key"**，无需信用卡即可创建免费 API key。

详细步骤：[官方文档](https://ai.google.dev/gemini-api/docs/api-key)

### 2. 安装依赖

```bash
pip install google-generativeai
```

或者从项目根目录安装完整依赖：

```bash
pip install -e .
```

### 3. 配置环境变量

在项目根目录创建或编辑 `.env` 文件：

```bash
# Gemini API Key (必需)
GEMINI_API_KEY=your-api-key-here

# 可选：选择其他模型
GEMINI_MODEL_ID=gemini-3.1-flash-lite
```

**兼容性说明**：也支持 `VLM_API_KEY` 环境变量，方便切换不同模型提供商。

### 4. 运行任务

使用 Gemini 作为推理模型：

```bash
python -m seetouch run "在哔哩哔哩搜索采莲曲" --reasoner gemini
```

使用 Doubao（火山引擎）模型：

```bash
python -m seetouch run "在哔哩哔哩搜索采莲曲" --reasoner doubao
```

## 编程接口

### 基础用法

```python
from PIL import Image
from seetouch.reasoning.gemini import GeminiReasoner, GeminiConfig

# 方式 1：从环境变量加载
reasoner = GeminiReasoner()

# 方式 2：手动配置
config = GeminiConfig(
    api_key="your-api-key",
    model_id="gemini-3.1-flash-lite",
)
reasoner = GeminiReasoner(config)

# 执行推理
screenshot = Image.open("screenshot.png")
result = reasoner.predict(
    instruction="在哔哩哔哩搜索采莲曲",
    screenshot=screenshot,
    history=[],
)

print(result.action)  # Action(type='CLICK', parameters={'point': [500, 100]})
print(result.screen_summary)
print(result.action_summary)
```

### 切换模型

```python
# 使用 Flash（更平衡）
config = GeminiConfig(
    api_key="your-api-key",
    model_id="gemini-2.5-flash",
)

# 使用 Pro（更强推理）
config = GeminiConfig(
    api_key="your-api-key",
    model_id="gemini-2.5-pro",
)
```

### 自定义生成参数

```python
config = GeminiConfig(
    api_key="your-api-key",
    temperature=0.8,      # 控制随机性（0-1）
    top_p=0.9,            # 核采样参数
    max_tokens=2048,      # 最大输出 token 数
    history_window=8,     # 历史窗口大小
)
reasoner = GeminiReasoner(config)
```

## 技术实现

### 核心特性

1. **直接传入 PIL Image**：Gemini Python SDK 原生支持 PIL Image，无需手动 base64 编码
2. **自动重试**：API 错误时返回 COMPLETE 动作并终止任务
3. **解析降级**：模型输出无法解析时降级为 WAIT，等待后重试
4. **Token 统计**：自动提取并记录 input/output tokens

### 与 DoubaoReasoner 的对比

| 特性 | GeminiReasoner | DoubaoReasoner |
|------|----------------|----------------|
| 免费额度 | 15 RPM / 500 RPD | 视火山引擎配额 |
| 思维链 | 不支持（无 thinking 模式） | 支持 VisualCoT |
| 图像输入 | 直接传 PIL Image | base64 data URL |
| API 兼容性 | Gemini 原生 SDK | OpenAI-compatible |
| 推荐场景 | 免费原型、高频调用 | 需要思维链推理 |

### 代码结构

```
seetouch/reasoning/
├── base.py          # Reasoner 协议定义
├── doubao.py        # Doubao 实现
├── gemini.py        # Gemini 实现（新增）
├── parser.py        # 统一的动作解析器
├── prompts.py       # 统一的 prompt 模板
└── __init__.py      # 导出所有 Reasoner
```

## 常见问题

### Q: 如何查看实际的速率限制？

A: 登录 [Google AI Studio](https://aistudio.google.com)，在项目设置中查看当前配额。官方文档不再保证公开的固定限制。

### Q: 超出速率限制怎么办？

A: 遇到 429 错误时：
1. 降低调用频率（增加 WAIT 延迟）
2. 切换到更低频率的模型（如 gemini-2.5-pro）
3. 升级到付费层级（Tier 1: 150-300 RPM）

参考：[429 错误解决方案](https://www.aifreeapi.com/en/posts/fix-gemini-flash-image-429-rate-limit)

### Q: Gemini 支持思维链（thinking mode）吗？

A: 目前 GeminiReasoner 不支持类似 Doubao 的 `thinking_mode` 参数。Gemini 的推理过程隐式进行，不暴露中间思考步骤。如果需要思维链，建议使用 DoubaoReasoner。

### Q: 如何在调试器中使用 Gemini？

A: 启动调试器前设置 `GEMINI_API_KEY` 并指定 Gemini 后端：

```bash
export GEMINI_API_KEY=your-api-key
python -m seetouch debug --reasoner gemini
```

### Q: 付费升级需要多少成本？

A: Gemini 3.1 Flash-Lite 定价（付费层）：
- 输入：$0.25 / 100 万 tokens
- 输出：$1.50 / 100 万 tokens

新用户有 $300 免费额度，足够测试约 2,238 张图像。

参考：[官方定价](https://ai.google.dev/gemini-api/docs/pricing)

## 进阶配置

### 多模型负载均衡

```python
import random
from seetouch.reasoning.gemini import GeminiReasoner, GeminiConfig

# 创建多个 API key 的 reasoner 池（注意：多 key 不增加配额）
reasoners = [
    GeminiReasoner(GeminiConfig(api_key=key))
    for key in ["key1", "key2", "key3"]
]

# 随机选择（仅用于演示，实际不推荐）
reasoner = random.choice(reasoners)
```

**注意**：根据 [官方说明](https://blog.laozhang.ai/en/posts/gemini-api-free-tier)，多个 API key 不会累加配额，限制是按项目级别的。

### 集成到自定义 Runner

```python
from seetouch.core.runner import Runner
from seetouch.reasoning.gemini import GeminiReasoner
from seetouch.device.android.controller import AndroidController
from seetouch.safety.guard import Guard

device = AndroidController()
reasoner = GeminiReasoner()
guard = Guard()

runner = Runner(
    device=device,
    reasoner=reasoner,
    guard=guard,
    runs_dir="./my_runs",
)

from seetouch.core.task import Task
task = Task(instruction="在哔哩哔哩搜索采莲曲", max_steps=30)
result = runner.run(task)
```

## 测试

运行 Gemini 相关单元测试：

```bash
pytest tests/test_gemini_reasoner.py -v
```

集成测试（需要真实 API key）：

```bash
export GEMINI_API_KEY=your-api-key
pytest tests/test_gemini_integration.py -v
```

## 相关资源

- [官方文档 - 图像理解](https://ai.google.dev/gemini-api/docs/image-understanding)
- [官方文档 - 速率限制](https://ai.google.dev/gemini-api/docs/rate-limits)
- [官方文档 - 定价](https://ai.google.dev/gemini-api/docs/pricing)
- [完整 API 参考](https://googleapis.github.io/python-genai/)
- [Gemini 3.1 Flash-Lite 模型卡](https://deepmind.google/models/model-cards/gemini-3-1-flash-lite/)

## 许可证

本集成代码遵循项目主许可证 Apache-2.0。Google Gemini API 使用需遵守 [Google API 服务条款](https://policies.google.com/terms)。
