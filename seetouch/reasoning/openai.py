"""OpenAI-compatible multimodal Chat Completions and Responses reasoner."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from PIL import Image

from ..core.action import ACTION_WAIT, Action, ActionOutput
from ..core.exceptions import VLMAPIError
from ..perception.screen import encode_image_data_url
from .base import StepRecord
from .parser import ParseError, parse_model_output
from .prompts import build_history_summary, build_system_prompt, extract_summary_fields


logger = logging.getLogger(__name__)


@dataclass
class OpenAIConfig:
    api_key: str
    model_id: str
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 60.0
    max_retries: int = 1
    history_window: int = 8
    api_mode: str = "chat_completions"

    def __post_init__(self) -> None:
        if not self.api_key.strip() or not self.model_id.strip():
            raise ValueError("OPENAI_API_KEY and OPENAI_MODEL_ID are required")
        self.base_url = self.base_url.strip().rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OPENAI_BASE_URL must be an HTTP(S) API base URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OPENAI_BASE_URL must not contain credentials, query or fragment")
        if self.base_url.endswith(("/chat/completions", "/responses")):
            raise ValueError("OPENAI_BASE_URL must exclude /chat/completions and /responses")
        if self.api_mode not in {"chat_completions", "responses"}:
            raise ValueError("OPENAI_API_MODE must be chat_completions or responses")
        if self.timeout <= 0 or self.max_retries < 0:
            raise ValueError("OPENAI_TIMEOUT must be positive; OPENAI_MAX_RETRIES must be >= 0")

    @classmethod
    def from_env(cls) -> "OpenAIConfig":
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model_id=os.environ.get("OPENAI_MODEL_ID", ""),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=float(os.environ.get("OPENAI_TIMEOUT", "60")),
            max_retries=int(os.environ.get("OPENAI_MAX_RETRIES", "1")),
            api_mode=os.environ.get("OPENAI_API_MODE", "chat_completions"),
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
        if self._config.api_mode == "responses" and not hasattr(self._client, "responses"):
            self._client.close()
            raise RuntimeError("Responses requires openai>=1.66.0; upgrade the OpenAI SDK")

    def predict(
        self, instruction: str, screenshot: Image.Image, history: list[StepRecord]
    ) -> ActionOutput:
        history_text = build_history_summary(history, n_recent=self._config.history_window)
        prompt = build_system_prompt(instruction, history_text)
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": encode_image_data_url(screenshot)}},
            ],
        }]
        logger.info(
            "[API call] provider=openai model=%s protocol=%s",
            self._config.model_id, self._config.api_mode,
        )
        try:
            reasoning = ""
            if self._config.api_mode == "responses":
                response = self._client.responses.create(
                    model=self._config.model_id,
                    input=[{"role": "user", "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": encode_image_data_url(screenshot)},
                    ]}],
                    store=False,
                )
                if response.status != "completed":
                    raise ValueError(f"Responses request did not complete: {response.status}")
                raw_output = response.output_text
                input_field, output_field = "input_tokens", "output_tokens"
            else:
                response = self._client.chat.completions.create(
                    model=self._config.model_id, messages=messages,
                )
                message = response.choices[0].message
                raw_output = message.content
                reasoning = getattr(message, "reasoning_content", None)
                if response.choices[0].finish_reason == "length":
                    raise ValueError("Model output was truncated (finish_reason=length)")
                input_field, output_field = "prompt_tokens", "completion_tokens"
            if not isinstance(raw_output, str) or not raw_output.strip():
                raise ValueError("Model returned no text; check refusal or output limits")
            usage = None
            if response.usage is not None:
                usage = {
                    "input_tokens": getattr(response.usage, input_field, 0) or 0,
                    "output_tokens": getattr(response.usage, output_field, 0) or 0,
                    "total_tokens": response.usage.total_tokens or 0,
                }
        except Exception as exc:
            raise VLMAPIError(str(exc)) from exc

        summary = extract_summary_fields(raw_output)
        try:
            action = parse_model_output(raw_output, screenshot.size)
        except ParseError:
            logger.warning("OpenAI model output could not be parsed; waiting before retry")
            action = Action(type=ACTION_WAIT, parameters={})
            summary["action_summary"] = "模型输出无法解析，等待后重试"
        return ActionOutput(
            action=action,
            raw_output=raw_output,
            screen_summary=summary.get("screen_summary", ""),
            action_summary=summary.get("action_summary", ""),
            usage=usage,
            prompt_text=f"{prompt}\n\n[截图]",
            reasoning_content=reasoning if isinstance(reasoning, str) else "",
        )
