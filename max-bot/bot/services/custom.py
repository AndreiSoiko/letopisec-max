"""Обработка транскрибации с пользовательским промтом через OpenRouter LLM."""

import logging

from bot.config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from bot.utils.http import get_client

logger = logging.getLogger(__name__)

LLM_URL = "https://openrouter.ai/api/v1/chat/completions"


async def process_with_custom_prompt(text: str, user_prompt: str) -> str:
    """Обработать текст транскрибации с пользовательским промтом."""
    if not OPENROUTER_API_KEY:
        return ""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://transcription-bot.local",
        "X-Title": "Transcription Bot",
    }

    truncated = text[:12000]
    if len(text) > 12000:
        truncated += "\n\n[... текст сокращён для анализа ...]"

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты — помощник для обработки результатов распознавания речи. "
                    "Выполни задание пользователя на основе предоставленного текста транскрибации. "
                    "Отвечай на том же языке, на котором написан текст транскрибации."
                ),
            },
            {
                "role": "user",
                "content": f"Задание: {user_prompt}\n\nТекст транскрибации:\n\n{truncated}",
            },
        ],
        "temperature": 0.4,
        "max_tokens": 3000,
    }

    try:
        async with get_client(timeout=120) as client:
            response = await client.post(LLM_URL, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"Custom prompt error ({response.status_code}): {response.text[:200]}")
                return ""
            result = response.json()
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"Ошибка обработки с промтом: {e}")

    return ""
