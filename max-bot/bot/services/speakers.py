"""Идентификация спикеров по имени через OpenRouter LLM."""

import json
import logging
import re

from bot.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, SPEAKER_IDENTIFICATION_PROMPT
from bot.utils.http import get_client

logger = logging.getLogger(__name__)

LLM_URL = "https://openrouter.ai/api/v1/chat/completions"
_MAX_TEXT_CHARS = 20_000


def _extract_json(raw: str) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as e:
        logger.warning(f"Speaker LLM: JSON parse error: {e} | raw={raw[:200]}")
        return {}
    result = {}
    for k, v in data.items():
        if isinstance(k, str) and k.isdigit() and isinstance(v, str) and v.strip():
            result[k] = v.strip()
    return result


async def identify_speakers(text: str) -> dict[str, str]:
    """Найти имена спикеров по самопредставлениям в тексте. Возвращает {speaker_id: name}."""
    if not OPENROUTER_API_KEY:
        return {}
    truncated = text[:_MAX_TEXT_CHARS]
    if len(text) > _MAX_TEXT_CHARS:
        truncated += "\n\n[... текст сокращён ...]"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://transcription-bot.local",
        "X-Title": "Transcription Bot",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SPEAKER_IDENTIFICATION_PROMPT},
            {"role": "user", "content": f"Найди самопредставления участников и верни JSON-маппинг.\n\n{truncated}"},
        ],
        "temperature": 0.1,
        "max_tokens": 300,
    }
    try:
        async with get_client(timeout=60) as client:
            response = await client.post(LLM_URL, headers=headers, json=payload)
        if response.status_code != 200:
            logger.warning(f"Speaker identification HTTP {response.status_code}: {response.text[:200]}")
            return {}
        raw_content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        mapping = _extract_json(raw_content)
        if mapping:
            logger.info(f"Identified speakers: {mapping}")
        else:
            logger.info("Speaker identification: no names found")
        return mapping
    except Exception as e:
        logger.warning(f"Speaker identification failed (non-fatal): {e}")
        return {}


def apply_speaker_names(text: str, mapping: dict[str, str]) -> str:
    """Заменить «Участник N:» на реальные имена из маппинга."""
    if not mapping:
        return text
    for speaker_id, name in mapping.items():
        text = re.sub(rf"^Участник {re.escape(speaker_id)}:", f"{name}:", text, flags=re.MULTILINE)
    return text
