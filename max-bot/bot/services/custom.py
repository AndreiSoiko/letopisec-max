"""Обработка транскрибации с пользовательским промтом через YandexGPT."""

import logging

from bot.config import YANDEX_API_KEY
from bot.services.yandex_llm import yandex_llm

logger = logging.getLogger(__name__)

_MAX_CHARS = 30000
_SYSTEM_PROMPT = (
    "Ты — помощник для обработки результатов распознавания речи. "
    "Выполни задание пользователя на основе предоставленного текста транскрибации. "
    "Отвечай на том же языке, на котором написан текст транскрибации."
)


async def process_with_custom_prompt(text: str, user_prompt: str) -> str:
    if not YANDEX_API_KEY:
        return ""
    truncated = text[:_MAX_CHARS]
    if len(text) > _MAX_CHARS:
        truncated += "\n\n[... текст сокращён для анализа ...]"
    return await yandex_llm(
        system_prompt=_SYSTEM_PROMPT,
        user_text=f"Задание: {user_prompt}\n\nТекст транскрибации:\n\n{truncated}",
        temperature=0.4,
        max_tokens=3000,
    )
