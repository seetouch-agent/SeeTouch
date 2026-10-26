"""Gemini Reasoner: 使用 Google Gemini API 的多模态推理器。

默认使用 Gemini 3.1 Flash-Lite 免费模型 (15 RPM / 500 RPD)。
支持其他 Gemini 模型切换。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from PIL import Image

from ..core.action import ACTION_WAIT, Action, ActionOutput
from ..core.exceptions import VLMAPIError
from .base import StepRecord
from .parser import ParseError, parse_model_output
from ..harness.context import bind_budget, compact_history, estimate_tokens
from .prompts import build_user_block, extract_summary_fields, static_system_prompt


logger = logging.getLogger(__name__)


# Gemini 免费模型列表
DEFAULT_MODEL_ID = "gemini-3.1-flash-lite"  # 15 RPM / 500 RPD (推荐)
GEMINI_FREE_MODELS = {
    "gemini-3.1-flash-lite": "15 RPM / 500 RPD - 最高频率，低延迟",
    "gemini-2.5-flash": "10 RPM / 250 RPD - 平衡性能",
    "gemini-2.5-pro": "5 RPM / 100 RPD - 更强推理",
}


@dataclass
class GeminiConfig:
    """Gemini API 配置。"""

    api_key: str
    model_id: str = DEFAULT_MODEL_ID
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    history_window: int = 0
    context_tokens: int = 64000

    @classmethod
    def from_env(cls) -> "GeminiConfig":
        """从环境变量加载配置。

        环境变量:
        - GEMINI_API_KEY 或 VLM_API_KEY: API key (必需)
        - GEMINI_MODEL_ID: 模型 ID (可选，默认 gemini-3.1-flash-lite)
        - SEETOUCH_THINKING_MODE: 保留兼容性，Gemini 不使用
        """
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("VLM_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "missing GEMINI_API_KEY (or VLM_API_KEY) environment variable. "
                "Get free API key at: https://aistudio.google.com"
            )
        return cls(
            api_key=api_key,
            model_id=os.environ.get("GEMINI_MODEL_ID", DEFAULT_MODEL_ID),
        )


class GeminiReasoner:
    """使用 Google Gemini API 的多模态推理器。

    支持 Gemini 免费模型:
    - gemini-3.1-flash-lite (默认): 15 RPM / 500 RPD
    - gemini-2.5-flash: 10 RPM / 250 RPD
    - gemini-2.5-pro: 5 RPM / 100 RPD
    """

    def __init__(self, config: GeminiConfig | None = None):
        self._config = config or GeminiConfig.from_env()
        try:
            import google.generativeai as genai
            self._genai = genai
        except ImportError as exc:
            raise RuntimeError(
                "google-generativeai package missing. run: pip install google-generativeai"
            ) from exc

        self._genai.configure(api_key=self._config.api_key)

        # 配置生成参数
        generation_config = {}
        if self._config.temperature is not None:
            generation_config["temperature"] = self._config.temperature
        if self._config.top_p is not None:
            generation_config["top_p"] = self._config.top_p
        if self._config.max_tokens is not None:
            generation_config["max_output_tokens"] = self._config.max_tokens

        self._model = genai.GenerativeModel(
            model_name=self._config.model_id,
            generation_config=generation_config if generation_config else None,
        )

        logger.info(
            "[Gemini] initialized with model=%s (free tier: %s)",
            self._config.model_id,
            GEMINI_FREE_MODELS.get(self._config.model_id, "unknown model"),
        )

    def predict(
        self,
        instruction: str,
        screenshot: Image.Image,
        history: list[StepRecord],
    ) -> ActionOutput:
        """预测下一步动作。"""
        # 构建 prompt
        # 前缀缓存：静态规则放最前，任务/历史放后面，Gemini 的隐式缓存按前缀命中
        system_text = static_system_prompt()
        budget = bind_budget(max_tokens=getattr(self._config, "context_tokens", 64000))
        history_text = compact_history(
            history,
            budget=budget,
            fixed_tokens=estimate_tokens(system_text) + estimate_tokens(instruction),
        ).text
        system_prompt = build_user_block(instruction, history_text)
        prompt_text = f"{system_text}\n\n{system_prompt}\n\n[截图]"

        try:
            # 调用 Gemini API
            # Gemini API 直接接受 PIL Image 对象
            response = self._model.generate_content([system_text, system_prompt, screenshot])

            # 阻塞等待生成完成
            response.resolve()

            raw_output = response.text
            usage = self._extract_usage(response)

        except Exception as exc:
            logger.error("gemini api call failed: %s", exc)
            raise VLMAPIError(f"{type(exc).__name__}: {exc}") from exc

        # 提取 summary 字段
        summary = extract_summary_fields(raw_output)

        # 解析动作
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
                parse_error=True,
            )

        return ActionOutput(
            action=action,
            raw_output=raw_output,
            screen_summary=summary.get("screen_summary", ""),
            action_summary=summary.get("action_summary", ""),
            usage=usage,
            prompt_text=prompt_text,
        )

    def _extract_usage(self, response: Any) -> dict[str, Any] | None:
        """提取 token 使用量。"""
        try:
            metadata = response.usage_metadata
            if metadata is None:
                return None
            return {
                "input_tokens": getattr(metadata, "prompt_token_count", 0),
                "output_tokens": getattr(metadata, "candidates_token_count", 0),
                "total_tokens": getattr(metadata, "total_token_count", 0),
            }
        except Exception:
            return None
