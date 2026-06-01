"""Выделение ключевых тезисов через YandexGPT."""

import logging

from bot.config import YANDEX_API_KEY, THESES_SYSTEM_PROMPT
from bot.services.yandex_llm import yandex_llm

logger = logging.getLogger(__name__)

_MAX_CHARS = 30000


async def extract_theses(text: str) -> str:
    if not YANDEX_API_KEY:
        return ""
    truncated = text[:_MAX_CHARS]
    if len(text) > _MAX_CHARS:
        truncated += "\n\n[... текст сокращён для анализа ...]"
    return await yandex_llm(
        system_prompt=THESES_SYSTEM_PROMPT,
        user_text=f"Выдели основные тезисы:\n\n{truncated}",
        temperature=0.2,
        max_tokens=2000,
    )
