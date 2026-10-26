"""默认 Reasoner 实现:Doubao Vision via Volcengine OpenAI-compatible API。

不依赖比赛 BaseAgent,自己控制 model / API URL / 采样参数 / thinking 开关。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from PIL import Image

from ..core.action import ACTION_WAIT, Action, ActionOutput
from ..core.exceptions import VLMAPIError
from ..perception.screen import encode_image_data_url
from .base import StepRecord
from .parser import ParseError, parse_model_output
from ..harness.context import bind_budget, compact_history, estimate_tokens
from .prompts import build_user_block, extract_summary_fields, static_system_prompt


logger = logging.getLogger(__name__)


DEFAULT_API_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL_ID = "doubao-seed-1-6-vision-250815"

# Doubao thinking mode: 决定模型是否在内部做 VisualCoT 推理
#   "disabled" - 不思考,响应快、便宜,但复杂场景准确率低
#   "enabled"  - 总是思考,慢、贵,但准确率高
# 注意:doubao-seed-1-6-vision-250815 不支持 "auto",其他模型可能支持
THINKING_MODES = {"disabled", "enabled", "auto"}
DEFAULT_THINKING_MODE = "disabled"  # 默认不思考：更快更省


@dataclass
class DoubaoConfig:
    api_key: str
    api_url: str = DEFAULT_API_URL
    model_id: str = DEFAULT_MODEL_ID
    temperature: float | None = None
    top_p: float | None = None
    thinking_mode: str = DEFAULT_THINKING_MODE
    history_window: int = 0
    context_tokens: int = 64000
    timeout: float = 60.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if self.thinking_mode not in THINKING_MODES:
            raise ValueError(
                f"thinking_mode must be one of {THINKING_MODES}, got {self.thinking_mode!r}"
            )

    @classmethod
    def from_env(cls) -> "DoubaoConfig":
        api_key = os.environ.get("VLM_API_KEY") or os.environ.get("DOUBAO_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "missing VLM_API_KEY (or DOUBAO_API_KEY) environment variable"
            )
        return cls(
            api_key=api_key,
            api_url=os.environ.get("DOUBAO_API_URL", DEFAULT_API_URL),
            model_id=os.environ.get("DOUBAO_MODEL_ID", DEFAULT_MODEL_ID),
            thinking_mode=os.environ.get("SEETOUCH_THINKING_MODE", DEFAULT_THINKING_MODE),
        )


class DoubaoReasoner:
    """直连 Volcengine 的 Doubao Vision Reasoner。"""

    def __init__(self, config: DoubaoConfig | None = None):
        self._config = config or DoubaoConfig.from_env()
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package missing. run: pip install openai") from exc
        self._client = OpenAI(base_url=self._config.api_url, api_key=self._config.api_key,
                              timeout=self._config.timeout, max_retries=self._config.max_retries)

    def predict(
        self,
        instruction: str,
        screenshot: Image.Image,
        history: list[StepRecord],
    ) -> ActionOutput:
        messages = self._build_messages(instruction, screenshot, history)

        # 提取 prompt 文本(不含图片 base64),用于调试
        prompt_text = self._extract_prompt_text(messages)

        try:
            response = self._call_api(messages)
            raw_output = self._extract_response_text(response)
            reasoning_content = self._extract_reasoning_content(response)
            usage = self._extract_usage(response)
        except Exception as exc:
            logger.error("doubao api call failed: %s", exc)
            raise VLMAPIError(f"{type(exc).__name__}: {exc}") from exc

        summary = extract_summary_fields(raw_output)

        try:
            action = parse_model_output(raw_output, screenshot.size)
        except ParseError as exc:
            # 模型输出非法时不要假装任务完成。降级到 WAIT,让 runner 下一轮重新预测。
            # 真正"完成"应该来自模型的明确 COMPLETE 输出。
            logger.warning("parse model output failed: %s", exc)
            return ActionOutput(
                action=Action(type=ACTION_WAIT, parameters={}),
                raw_output=raw_output,
                screen_summary=summary.get("screen_summary", ""),
                action_summary="模型输出无法解析,降级为等待后重试",
                usage=usage,
                prompt_text=prompt_text,
                reasoning_content=reasoning_content,
                parse_error=True,
            )

        return ActionOutput(
            action=action,
            raw_output=raw_output,
            screen_summary=summary.get("screen_summary", ""),
            action_summary=summary.get("action_summary", ""),
            usage=usage,
            prompt_text=prompt_text,
            reasoning_content=reasoning_content,
        )

    # ---------------------------- 内部 ----------------------------

    def _build_messages(
        self,
        instruction: str,
        screenshot: Image.Image,
        history: list[StepRecord],
    ) -> list[dict[str, Any]]:
        # 前缀缓存：system 段每步逐字节相同，任务/历史/观测全部放在 user 段
        system_text = static_system_prompt()
        budget = bind_budget(max_tokens=getattr(self._config, "context_tokens", 64000))
        history_text = compact_history(
            history,
            budget=budget,
            fixed_tokens=estimate_tokens(system_text) + estimate_tokens(instruction),
        ).text
        user_text = build_user_block(instruction, history_text)
        return [
            {"role": "system", "content": system_text},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": encode_image_data_url(screenshot)},
                    },
                ],
            },
        ]

    def _call_api(self, messages: list[dict[str, Any]]) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._config.model_id,
            "messages": messages,
        }
        if self._config.temperature is not None:
            kwargs["temperature"] = self._config.temperature
        if self._config.top_p is not None:
            kwargs["top_p"] = self._config.top_p
        kwargs["extra_body"] = {"thinking": {"type": self._config.thinking_mode}}

        logger.info(
            "[API call] model=%s thinking=%s",
            self._config.model_id, self._config.thinking_mode,
        )
        return self._client.chat.completions.create(**kwargs)

    def _extract_response_text(self, response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except Exception:
            return str(response)
        if isinstance(content, str):
            return content
        import json
        return json.dumps(content, ensure_ascii=False)

    def _extract_reasoning_content(self, response: Any) -> str:
        """提取思维链文本。

        Doubao thinking 开启后,VisualCoT 推理内容放在 message.reasoning_content
        独立字段(不在 content 里)。thinking=disabled 时该字段缺失或为空。
        """
        try:
            message = response.choices[0].message
        except Exception:
            return ""
        reasoning = getattr(message, "reasoning_content", None)
        return reasoning if isinstance(reasoning, str) else ""

    def _extract_usage(self, response: Any) -> dict[str, Any] | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        out = {
            "input_tokens": getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
        # thinking 开启后,reasoning_tokens 反映思考用了多少 token
        details = (
            getattr(usage, "completion_tokens_details", None)
            or getattr(usage, "output_tokens_details", None)
        )
        if details is not None:
            reasoning = getattr(details, "reasoning_tokens", None)
            if reasoning:
                out["reasoning_tokens"] = reasoning
        return out

    def _extract_prompt_text(self, messages: list[dict[str, Any]]) -> str:
        """从 messages 中提取纯文本部分,用于调试显示。

        跳过 image_url 内容(base64 太长),只保留文本。
        """
        parts: list[str] = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append(item.get("text", ""))
                        elif item.get("type") == "image_url":
                            parts.append("[截图]")
        return "\n".join(parts)
