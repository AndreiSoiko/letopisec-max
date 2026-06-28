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
    "Ты — профессиональный переводчик и редактор. "
    "Тебе дан текст, полученный автоматическим распознаванием речи (STT) — он может содержать "
    "ошибки распознавания: неверные слова, искажённые имена и термины. "
    "Переведи текст на указанный язык, попутно исправляя очевидные STT-ошибки по контексту. "
    "Временны́е метки в формате [MM:SS] сохраняй на тех же местах в переводе. "
    "Верни ТОЛЬКО перевод без пояснений и комментариев."
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
        user_text=f"Переведи на {lang_name}, исправляя ошибки распознавания речи:\n\n{truncated}",
        temperature=0.1,
        max_tokens=4096,
    )
