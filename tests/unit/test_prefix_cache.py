"""前缀缓存：静态前缀稳定、消息分层、缓存命中统计。

前缀缓存的前提是"每次请求的开头字节完全相同"。这里锁死三件事：

1. 静态规则里不允许出现任何变量（否则每步都变，缓存永远不命中）；
2. 适配器把静态规则放在 messages[0]，动态内容放 messages[1]；
3. provider 报回来的 cached_tokens 要能进 usage，并累计到 Session。
"""

from types import SimpleNamespace

from openai import OpenAI
from PIL import Image

try:
    import httpx2 as httpx
except ImportError:
    import httpx

from seetouch.core.action import Action, ActionOutput
from seetouch.core.session import Session
from seetouch.core.task import Task
from seetouch.reasoning.openai import OpenAIConfig, OpenAIReasoner, _cached_tokens
from seetouch.reasoning.prompts import (
    build_system_prompt,
    build_user_block,
    static_system_prompt,
)


def test_static_prompt_is_byte_identical_across_calls():
    first = static_system_prompt()
    second = static_system_prompt()
    assert first == second
    assert len(first) > 1000


def test_static_prompt_has_no_placeholders():
    text = static_system_prompt()
    assert "{instruction}" not in text
    assert "{history}" not in text


def test_user_block_carries_task_history_and_pinned_inputs():
    block = build_user_block(
        "打开设置", "Step 1: CLICK", pinned_inputs="问题：A\n回答：B"
    )
    assert block.startswith("用户任务:\n打开设置")
    assert "回答：B" in block
    assert block.index("回答：B") < block.index("历史动作摘要")
    assert block.rstrip().endswith("Step 1: CLICK")


def test_pinned_inputs_come_before_history():
    block = build_user_block("任务", "历史", pinned_inputs="用户要求")
    assert block.index("用户要求") < block.index("历史")


def test_legacy_build_system_prompt_still_contains_task():
    text = build_system_prompt("打开设置", "Step 1: CLICK")
    assert text.startswith(static_system_prompt())
    assert "打开设置" in text


def test_cached_tokens_reads_both_provider_shapes():
    chat = SimpleNamespace(prompt_tokens_details=SimpleNamespace(cached_tokens=42))
    responses = SimpleNamespace(input_tokens_details=SimpleNamespace(cached_tokens=7))
    assert _cached_tokens(chat) == 42
    assert _cached_tokens(responses) == 7
    assert _cached_tokens(SimpleNamespace()) == 0


def _response_body(text='{"action":"COMPLETE","parameters":{}}', cached=0):
    usage = {"prompt_tokens": 1200, "completion_tokens": 10, "total_tokens": 1210}
    if cached:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return {
        "id": "t", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": text}}],
        "usage": usage,
    }


def test_requests_keep_a_stable_system_prefix_across_steps():
    payloads = []

    def handler(request):
        import json
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=_response_body(cached=900 if len(payloads) > 1 else 0))

    config = OpenAIConfig("key", "m", "https://proxy.example/v1")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with OpenAI(api_key="key", base_url="https://proxy.example/v1", http_client=http_client) as client:
            reasoner = OpenAIReasoner(config)
            reasoner._client = client
            image = Image.new("RGB", (64, 64))
            from seetouch.reasoning.base import StepRecord
            reasoner.predict("打开设置", image, [])
            reasoner.predict(
                "打开设置", image,
                [StepRecord(step=1, action=Action("CLICK", {"point": [500, 250]}))],
            )

    assert len(payloads) == 2
    assert payloads[0]["messages"][0]["role"] == "system"
    assert payloads[0]["messages"][0] == payloads[1]["messages"][0]
    # 第二步应该拿到缓存命中数
    assert payloads[1]["messages"][1]["content"][0]["type"] == "text"


def test_cached_tokens_accumulate_in_session(tmp_path):
    session = Session(Task("t", task_id="cache"), tmp_path)
    session.account_prediction({"input_tokens": 100, "output_tokens": 10, "cached_tokens": 80})
    session.account_prediction({"input_tokens": 50, "output_tokens": 5, "cached_tokens": 20})
    result = session.summarize()
    assert result.total_cached_tokens == 100
    assert result.total_tokens == 165


def test_usage_reports_cache_hits_from_provider(tmp_path):
    def handler(request):
        return httpx.Response(200, json=_response_body(cached=777))

    config = OpenAIConfig("key", "m", "https://proxy.example/v1")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with OpenAI(api_key="key", base_url="https://proxy.example/v1", http_client=http_client) as client:
            reasoner = OpenAIReasoner(config)
            reasoner._client = client
            out: ActionOutput = reasoner.predict("任务", Image.new("RGB", (32, 32)), [])
    assert out.usage is not None
    assert out.usage["cached_tokens"] == 777
