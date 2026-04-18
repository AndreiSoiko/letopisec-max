"""Составление протокола совещания через OpenRouter LLM."""

import logging

from bot.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, PROTOCOL_SYSTEM_PROMPT
from bot.utils.http import get_client

logger = logging.getLogger(__name__)

LLM_URL = "https://openrouter.ai/api/v1/chat/completions"


async def extract_protocol(text: str) -> str:
    """Составить протокол совещания из транскрибации."""
    if not OPENROUTER_API_KEY:
        return ""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://transcription-bot.local",
        "X-Title": "Transcription Bot",
    }

    truncated = text[:15000]
    if len(text) > 15000:
        truncated += "\n\n[... текст сокращён для анализа ...]"

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": PROTOCOL_SYSTEM_PROMPT},
            {"role": "user", "content": f"Составь протокол совещания:\n\n{truncated}"},
        ],
        "temperature": 0.2,
        "max_tokens": 3000,
    }

    try:
        async with get_client(timeout=120) as client:
            response = await client.post(LLM_URL, headers=headers, json=payload)

            if response.status_code != 200:
                logger.error(f"Protocol error ({response.status_code}): {response.text[:200]}")
                return ""

            result = response.json()
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"Ошибка составления протокола: {e}")

    return ""
