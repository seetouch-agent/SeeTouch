"""Reasoner 选择与组装。"""

from __future__ import annotations

from .base import Reasoner
from .doubao import DoubaoReasoner
from .gemini import GeminiReasoner
from .openai_compatible import OpenAICompatibleReasoner


REASONER_NAMES = ("openai", "doubao", "gemini")
DEFAULT_REASONER = "openai"


def create_reasoner(name: str = DEFAULT_REASONER) -> Reasoner:
    if name == "openai":
        return OpenAICompatibleReasoner()
    if name == "doubao":
        return DoubaoReasoner()
    if name == "gemini":
        return GeminiReasoner()
    raise ValueError(f"unknown reasoner: {name}")
