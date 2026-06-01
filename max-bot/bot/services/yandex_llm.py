"""Общий клиент YandexGPT Foundation Models API."""

import logging

from bot.config import YANDEX_API_KEY, YANDEX_FOLDER_ID
from bot.utils.http import get_client

logger = logging.getLogger(__name__)

_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
_MODEL = "yandexgpt-32k"


async def yandex_llm(
    system_prompt: str,
    user_text: str,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> str:
    """Вызов YandexGPT. Raises при ошибке API."""
    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "x-folder-id": YANDEX_FOLDER_ID,
    }
    body = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{_MODEL}/latest",
        "completionOptions": {
            "stream": False,
            "temperature": temperature,
            "maxTokens": str(max_tokens),
        },
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": user_text},
        ],
    }

    async with get_client(timeout=120) as client:
        response = await client.post(_URL, headers=headers, json=body)

    if response.status_code != 200:
        raise Exception(f"YandexGPT {response.status_code}: {response.text[:300]}")

    alternatives = response.json().get("result", {}).get("alternatives", [])
    if alternatives:
        return alternatives[0].get("message", {}).get("text", "")
    return ""
