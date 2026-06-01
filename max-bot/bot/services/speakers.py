"""Идентификация спикеров по имени через YandexGPT."""

import json
import logging
import re

from bot.config import YANDEX_API_KEY, SPEAKER_IDENTIFICATION_PROMPT
from bot.services.yandex_llm import yandex_llm

logger = logging.getLogger(__name__)

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
    if not YANDEX_API_KEY:
        return {}
    truncated = text[:_MAX_TEXT_CHARS]
    if len(text) > _MAX_TEXT_CHARS:
        truncated += "\n\n[... текст сокращён ...]"
    try:
        raw_content = await yandex_llm(
            system_prompt=SPEAKER_IDENTIFICATION_PROMPT,
            user_text=f"Найди самопредставления участников и верни JSON-маппинг.\n\n{truncated}",
            temperature=0.1,
            max_tokens=300,
        )
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
