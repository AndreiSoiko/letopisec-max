"""Выделение ключевых тезисов из транскрибации через OpenRouter LLM."""

import logging

from bot.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, THESES_SYSTEM_PROMPT
from bot.utils.http import get_client

logger = logging.getLogger(__name__)

LLM_URL = "https://openrouter.ai/api/v1/chat/completions"


async def extract_theses(text: str) -> str:
    """Выделить основные тезисы из текста."""
    if not OPENROUTER_API_KEY:
        return ""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://transcription-bot.local",
        "X-Title": "Transcription Bot",
    }

    # Берём первые ~12000 символов (ограничение контекста)
    truncated = text[:12000]
    if len(text) > 12000:
        truncated += "\n\n[... текст сокращён для анализа ...]"

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": THESES_SYSTEM_PROMPT},
            {"role": "user", "content": f"Выдели основные тезисы:\n\n{truncated}"},
        ],
        "temperature": 0.2,
        "max_tokens": 2000,
    }

    try:
        async with get_client(timeout=120) as client:
            response = await client.post(LLM_URL, headers=headers, json=payload)

            if response.status_code != 200:
                logger.error(f"Theses extraction error ({response.status_code}): {response.text[:200]}")
                return ""

            result = response.json()
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"Ошибка выделения тезисов: {e}")

    return ""
