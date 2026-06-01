"""Контекстная коррекция транскрибации через YandexGPT."""

import asyncio
import logging
from typing import Optional, Callable

from bot.config import YANDEX_API_KEY, CORRECTION_SYSTEM_PROMPT
from bot.services.yandex_llm import yandex_llm

logger = logging.getLogger(__name__)

MAX_BLOCK_CHARS = 20000
OVERLAP_CHARS = 500


def _split_text(text: str) -> list[str]:
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


async def correct_transcription(
    raw_text: str,
    on_progress: Optional[Callable] = None,
) -> str:
    if not raw_text.strip():
        return raw_text
    if not YANDEX_API_KEY:
        logger.warning("YANDEX_API_KEY не задан, коррекция пропущена")
        return raw_text

    blocks = _split_text(raw_text)
    corrected = []

    for i, block in enumerate(blocks):
        for attempt in range(3):
            try:
                result = await yandex_llm(
                    system_prompt=CORRECTION_SYSTEM_PROMPT,
                    user_text=f"Исправь ошибки распознавания:\n\n{block}",
                    temperature=0.1,
                    max_tokens=4096,
                )
                corrected.append(result)
                break
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Ошибка коррекции блока {i + 1}/{len(blocks)}: {e}")
                    corrected.append(block)

        if on_progress:
            try:
                await on_progress(i + 1, len(blocks))
            except Exception:
                pass

    return _merge_blocks(corrected)
