"""OpenAI Chat Completions 兼容的多模态推理器。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image

from ..core.action import ACTION_COMPLETE, ACTION_WAIT, Action, ActionOutput
from ..perception.screen import encode_image_data_url
from .base import StepRecord
from .parser import ParseError, parse_model_output
from .prompts import build_history_summary, build_system_prompt, extract_summary_fields

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion


logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL_ID = "gpt-4.1-mini"
REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}


@dataclass
class OpenAICompatibleConfig:
    """OpenAI 兼容 API 配置。"""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model_id: str = DEFAULT_MODEL_ID
    reasoning_effort: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    history_window: int = 8

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.reasoning_effort = _parse_reasoning_effort(self.reasoning_effort)
        if not self.api_key:
            raise ValueError("api_key must not be empty")
        if not self.base_url:
            raise ValueError("base_url must not be empty")
        if not self.model_id:
            raise ValueError("model_id must not be empty")
        if (
            self.reasoning_effort is not None
            and self.reasoning_effort not in REASONING_EFFORTS
        ):
            raise ValueError(
                f"reasoning_effort must be one of {REASONING_EFFORTS} or None, "
                f"got {self.reasoning_effort!r}"
            )

    @classmethod
    def from_env(cls) -> "OpenAICompatibleConfig":
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VLM_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "missing OPENAI_API_KEY (or VLM_API_KEY) environment variable"
            )

        return cls(
            api_key=api_key,
            base_url=(
                os.environ.get("OPENAI_BASE_URL")
                or os.environ.get("OPENAI_API_URL")
                or DEFAULT_BASE_URL
            ),
            model_id=os.environ.get("OPENAI_MODEL_ID", DEFAULT_MODEL_ID),
            reasoning_effort=_parse_reasoning_effort(
                os.environ.get("OPENAI_REASONING_EFFORT")
                or os.environ.get("SEETOUCH_REASONING_EFFORT")
            ),
            temperature=_parse_float(os.environ.get("SEETOUCH_TEMPERATURE")),
            top_p=_parse_float(os.environ.get("SEETOUCH_TOP_P")),
            max_tokens=_parse_int(os.environ.get("OPENAI_MAX_TOKENS")),
            history_window=int(os.environ.get("SEETOUCH_HISTORY_WINDOW", "8")),
        )


class OpenAICompatibleReasoner:
    """通过 OpenAI Chat Completions 兼容接口预测下一步动作。"""

    def __init__(self, config: OpenAICompatibleConfig | None = None):
        self._config = config or OpenAICompatibleConfig.from_env()
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package missing. run: pip install openai") from exc
        self._client = OpenAI(
            base_url=self._config.base_url,
            api_key=self._config.api_key,
        )

    def predict(
        self,
        instruction: str,
        screenshot: Image.Image,
        history: list[StepRecord],
    ) -> ActionOutput:
        messages = self._build_messages(instruction, screenshot, history)
        prompt_text = self._extract_prompt_text(messages)

        try:
            response = self._call_api(messages)
            raw_output = self._extract_response_text(response)
            reasoning_content = self._extract_reasoning_content(response)
            usage = self._extract_usage(response)
        except Exception as exc:
            logger.error("openai-compatible api call failed: %s", exc)
            return ActionOutput(
                action=Action(type=ACTION_COMPLETE, parameters={}),
                raw_output=f"Error: {type(exc).__name__}: {exc}",
                screen_summary="",
                action_summary="API 调用失败,任务终止",
                prompt_text=prompt_text,
            )

        summary = extract_summary_fields(raw_output)
        try:
            action = parse_model_output(raw_output, screenshot.size)
        except ParseError as exc:
            logger.warning("parse model output failed: %s", exc)
            return ActionOutput(
                action=Action(type=ACTION_WAIT, parameters={}),
                raw_output=raw_output,
                screen_summary=summary.get("screen_summary", ""),
                action_summary="模型输出无法解析,降级为等待后重试",
                usage=usage,
                prompt_text=prompt_text,
                reasoning_content=reasoning_content,
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

    def _build_messages(
        self,
        instruction: str,
        screenshot: Image.Image,
        history: list[StepRecord],
    ) -> list[dict]:
        history_text = build_history_summary(history, n_recent=self._config.history_window)
        system_prompt = build_system_prompt(instruction, history_text)
        return [
            {"role": "user", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": encode_image_data_url(screenshot)},
                    }
                ],
            },
        ]

    def _call_api(self, messages: list[dict]) -> "ChatCompletion":
        kwargs: dict = {
            "model": self._config.model_id,
            "messages": messages,
        }
        if self._config.temperature is not None:
            kwargs["temperature"] = self._config.temperature
        if self._config.top_p is not None:
            kwargs["top_p"] = self._config.top_p
        if self._config.max_tokens is not None:
            kwargs["max_tokens"] = self._config.max_tokens
        if self._config.reasoning_effort is not None:
            kwargs["extra_body"] = {
                "reasoning_effort": self._config.reasoning_effort,
            }

        logger.info(
            "[API call] base_url=%s model=%s reasoning_effort=%s",
            self._config.base_url,
            self._config.model_id,
            self._config.reasoning_effort or "model-default",
        )
        return self._client.chat.completions.create(**kwargs)

    def _extract_response_text(self, response: "ChatCompletion") -> str:
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False)

    def _extract_reasoning_content(self, response: "ChatCompletion") -> str:
        message = response.choices[0].message.model_dump()
        for key in ("reasoning_content", "reasoning"):
            reasoning = message.get(key)
            if isinstance(reasoning, str):
                return reasoning
        return ""

    def _extract_usage(self, response: "ChatCompletion") -> dict | None:
        if response.usage is None:
            return None
        usage = response.usage.model_dump()
        out = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            reasoning_tokens = details.get("reasoning_tokens")
            if reasoning_tokens:
                out["reasoning_tokens"] = reasoning_tokens
        return out

    def _extract_prompt_text(self, messages: list[dict]) -> str:
        parts: list[str] = []
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        parts.append("[截图]")
        return "\n".join(parts)


def _parse_reasoning_effort(value: str | None) -> str | None:
    if value is None or value.strip().lower() in {"", "none", "default"}:
        return None
    return value.strip().lower()


def _parse_float(value: str | None) -> float | None:
    return float(value) if value else None


def _parse_int(value: str | None) -> int | None:
    return int(value) if value else None
