"""Контекстная коррекция транскрибации через OpenRouter LLM."""

import asyncio
import logging
from typing import Optional, Callable

from bot.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, CORRECTION_SYSTEM_PROMPT
from bot.utils.http import get_client

logger = logging.getLogger(__name__)

LLM_URL = "https://openrouter.ai/api/v1/chat/completions"

# Разбиение текста на блоки для LLM
MAX_BLOCK_CHARS = 10000
OVERLAP_CHARS = 500


def _split_text(text: str) -> list[str]:
    """Разбить текст на блоки."""
    if len(text) <= MAX_BLOCK_CHARS:
        return [text]

    blocks = []
    start = 0
    while start < len(text):
        end = start + MAX_BLOCK_CHARS
        if end < len(text):
            for sep in [". ", "? ", "! ", "\n\n", "\n"]:
                last = text.rfind(sep, start + MAX_BLOCK_CHARS // 2, end)
                if last > start:
                    end = last + len(sep)
                    break
        blocks.append(text[start:end])
        start = end - OVERLAP_CHARS
    return blocks


def _merge_blocks(blocks: list[str]) -> str:
    """Склеить блоки, убрав дубликаты на стыках."""
    if len(blocks) <= 1:
        return blocks[0] if blocks else ""

    result = blocks[0]
    for block in blocks[1:]:
        best = 0
        for j in range(20, min(OVERLAP_CHARS * 2, len(result), len(block))):
            if block.startswith(result[-j:]):
                best = j
                break
        result += block[best:] if best > 0 else (" " + block)
    return result


async def _call_llm(text: str) -> str:
    """Один запрос к OpenRouter LLM."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://transcription-bot.local",
        "X-Title": "Transcription Bot",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": CORRECTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Исправь ошибки распознавания:\n\n{text}"},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    async with get_client(timeout=120) as client:
        for attempt in range(3):
            try:
                response = await client.post(LLM_URL, headers=headers, json=payload)

                if response.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"OpenRouter rate limit, ожидание {wait}с...")
                    await asyncio.sleep(wait)
                    continue

                if response.status_code != 200:
                    logger.error(f"OpenRouter ошибка ({response.status_code}): {response.text[:200]}")
                    raise Exception(f"OpenRouter ошибка ({response.status_code})")

                result = response.json()
                choices = result.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", text)
                return text

            except Exception as e:
                if attempt < 2 and "timeout" in str(e).lower():
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

    return text


async def correct_transcription(
    raw_text: str,
    on_progress: Optional[Callable] = None,
) -> str:
    """
    Контекстная коррекция через OpenRouter.
    Возвращает скорректированный текст.
    """
    if not raw_text.strip():
        return raw_text

    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY не задан, коррекция пропущена")
        return raw_text

    blocks = _split_text(raw_text)
    corrected = []

    for i, block in enumerate(blocks):
        try:
            result = await _call_llm(block)
            corrected.append(result)
        except Exception as e:
            logger.error(f"Ошибка коррекции блока {i + 1}/{len(blocks)}: {e}")
            corrected.append(block)

        if on_progress:
            try:
                await on_progress(i + 1, len(blocks))
            except Exception:
                pass

    return _merge_blocks(corrected)
