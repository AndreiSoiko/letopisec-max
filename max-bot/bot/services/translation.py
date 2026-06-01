"""Перевод текста через YandexGPT."""

import logging

from bot.config import YANDEX_API_KEY
from bot.services.yandex_llm import yandex_llm

logger = logging.getLogger(__name__)

TRANSLATE_LANG_NAMES = {
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
    "de": "🇩🇪 Deutsch",
    "fr": "🇫🇷 Français",
    "es": "🇪🇸 Español",
}

_MAX_CHARS = 30000
_SYSTEM_PROMPT = (
    "Ты — профессиональный переводчик. "
    "Переведи текст точно, сохраняя структуру и форматирование. "
    "Верни ТОЛЬКО перевод без пояснений."
)


async def translate_text(text: str, target_lang: str) -> str:
    if not YANDEX_API_KEY:
        return ""
    lang_name = TRANSLATE_LANG_NAMES.get(target_lang, target_lang)
    truncated = text[:_MAX_CHARS]
    if len(text) > _MAX_CHARS:
        truncated += "\n\n[... текст сокращён ...]"
    return await yandex_llm(
        system_prompt=_SYSTEM_PROMPT,
        user_text=f"Переведи на {lang_name}:\n\n{truncated}",
        temperature=0.1,
        max_tokens=4096,
    )
