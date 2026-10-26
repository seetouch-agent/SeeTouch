"""OpenAI-compatible multimodal Chat Completions and Responses reasoner."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

from ..core.action import ACTION_WAIT, Action, ActionOutput
from ..core.exceptions import VLMAPIError
from ..perception.screen import encode_image_data_url
from .base import StepRecord
from .parser import ParseError, parse_model_output
from ..harness.context import bind_budget, compact_history, estimate_tokens
from .prompts import build_user_block, extract_summary_fields, static_system_prompt
from .responses_transport import create_response


logger = logging.getLogger(__name__)
REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}


@dataclass
class OpenAIConfig:
    api_key: str
    model_id: str
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 60.0
    max_retries: int = 1
    history_window: int = 0
    context_tokens: int = 64000
    api_mode: str = "chat_completions"
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        if not self.api_key.strip() or not self.model_id.strip():
            raise ValueError("OPENAI_API_KEY and OPENAI_MODEL_ID are required")
        self.api_key = self.api_key.strip()
        self.model_id = self.model_id.strip()
        self.base_url = self.base_url.strip().rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OPENAI_BASE_URL must be an HTTP(S) API base URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OPENAI_BASE_URL must not contain credentials, query or fragment")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("OPENAI_BASE_URL has an invalid port")
        if self.base_url.endswith(("/chat/completions", "/responses")):
            raise ValueError("OPENAI_BASE_URL must exclude /chat/completions and /responses")
        if self.api_mode not in {"chat_completions", "responses"}:
            raise ValueError("OPENAI_API_MODE must be chat_completions or responses")
        if not math.isfinite(self.timeout) or self.timeout <= 0 or self.max_retries < 0:
            raise ValueError("OPENAI_TIMEOUT must be positive; OPENAI_MAX_RETRIES must be >= 0")
        if self.reasoning_effort is not None:
            self.reasoning_effort = self.reasoning_effort.strip().lower()
            if self.reasoning_effort in {"", "default"}:
                self.reasoning_effort = None
            elif self.reasoning_effort not in REASONING_EFFORTS:
                raise ValueError("Unsupported OPENAI_REASONING_EFFORT")

    @classmethod
    def from_env(cls) -> "OpenAIConfig":
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model_id=os.environ.get("OPENAI_MODEL_ID", ""),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=float(os.environ.get("OPENAI_TIMEOUT", "60")),
            max_retries=int(os.environ.get("OPENAI_MAX_RETRIES", "1")),
            api_mode=os.environ.get("OPENAI_API_MODE", "chat_completions"),
            reasoning_effort=os.environ.get("OPENAI_REASONING_EFFORT"),
            context_tokens=int(os.environ.get("SEETOUCH_CONTEXT_TOKENS", "64000")),
        )


class OpenAIReasoner:
    def __init__(self, config: OpenAIConfig | None = None):
        from openai import OpenAI

        self._config = config or OpenAIConfig.from_env()
        self._client = OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout,
            max_retries=self._config.max_retries,
        )
        if (
            self._config.api_mode == "responses"
            and not callable(getattr(getattr(self._client, "responses", None), "create", None))
            and not callable(getattr(self._client, "post", None))
        ):
            self._client.close()
            raise RuntimeError("Responses requires openai>=1.66.0; upgrade the OpenAI SDK")

    def predict(
        self, instruction: str, screenshot: Image.Image, history: list[StepRecord]
    ) -> ActionOutput:
        # 前缀缓存：system 段每一步逐字节相同，动态内容全部放在 user 段
        system_text = static_system_prompt()
        budget = bind_budget(max_tokens=self._config.context_tokens)
        history_text = compact_history(
            history,
            budget=budget,
            fixed_tokens=estimate_tokens(system_text) + estimate_tokens(instruction),
        ).text
        prompt = build_user_block(instruction, history_text)
        messages = [
            {"role": "system", "content": system_text},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": encode_image_data_url(screenshot)}},
                ],
            },
        ]
        logger.info(
            "[API call] provider=openai model=%s protocol=%s",
            self._config.model_id, self._config.api_mode,
        )
        try:
            reasoning = ""
            if self._config.api_mode == "responses":
                options = {}
                if self._config.reasoning_effort is not None:
                    options["reasoning"] = {"effort": self._config.reasoning_effort}
                response = create_response(
                    self._client,
                    model=self._config.model_id,
                    input=[
                        {"role": "system", "content": [
                            {"type": "input_text", "text": system_text},
                        ]},
                        {"role": "user", "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": encode_image_data_url(screenshot)},
                        ]},
                    ],
                    store=False,
                    **options,
                )
                if response.status != "completed":
                    raise ValueError(f"Responses request did not complete: {response.status}")
                raw_output = response.output_text
                input_field, output_field = "input_tokens", "output_tokens"
            else:
                options = {}
                if self._config.reasoning_effort is not None:
                    # extra_body also works with the Android SDK (openai 1.30).
                    options["extra_body"] = {"reasoning_effort": self._config.reasoning_effort}
                response = self._client.chat.completions.create(
                    model=self._config.model_id, messages=messages,
                    **options,
                )
                message = response.choices[0].message
                raw_output = message.content
                reasoning = getattr(message, "reasoning_content", None)
                finish_reason = response.choices[0].finish_reason
                if finish_reason != "stop":
                    raise ValueError(f"Model output did not complete (finish_reason={finish_reason})")
                input_field, output_field = "prompt_tokens", "completion_tokens"
            if not isinstance(raw_output, str) or not raw_output.strip():
                raise ValueError("Model returned no text; check refusal or output limits")
            usage = None
            if response.usage is not None:
                usage = {
                    "input_tokens": getattr(response.usage, input_field, 0) or 0,
                    "output_tokens": getattr(response.usage, output_field, 0) or 0,
                    "total_tokens": response.usage.total_tokens or 0,
                    "cached_tokens": _cached_tokens(response.usage),
                }
        except Exception as exc:
            raise VLMAPIError(str(exc)) from exc

        summary = extract_summary_fields(raw_output)
        parse_error = False
        try:
            action = parse_model_output(raw_output, screenshot.size)
        except ParseError:
            logger.warning("OpenAI model output could not be parsed; waiting before retry")
            action = Action(type=ACTION_WAIT, parameters={})
            summary["action_summary"] = "模型输出无法解析，等待后重试"
            parse_error = True
        return ActionOutput(
            action=action,
            raw_output=raw_output,
            screen_summary=summary.get("screen_summary", ""),
            action_summary=summary.get("action_summary", ""),
            usage=usage,
            prompt_text=f"{system_text}\n\n{prompt}\n\n[截图]",
            reasoning_content=reasoning if isinstance(reasoning, str) else "",
            parse_error=parse_error,
        )


def _cached_tokens(usage: Any) -> int:
    """读取 provider 报回来的前缀缓存命中量（不同协议字段名不同）。"""
    for attr in ("prompt_tokens_details", "input_tokens_details"):
        details = getattr(usage, attr, None)
        if details is not None:
            value = getattr(details, "cached_tokens", 0)
            if isinstance(value, int) and value > 0:
                return value
    return 0
