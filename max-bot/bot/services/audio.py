"""Обработка аудио/видео: извлечение звука, конвертация, нарезка через ffmpeg."""

import asyncio
import json
import logging
from pathlib import Path
from typing import List, Tuple

from bot.config import CHUNK_DURATION_SEC, CHUNK_OVERLAP_SEC

logger = logging.getLogger(__name__)


async def _run_ffmpeg(args: list, timeout: int = 600) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise Exception("ffmpeg таймаут")
    if process.returncode != 0:
        raise Exception(f"ffmpeg ошибка: {stderr.decode()[:300]}")


async def _run_ffprobe(file_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(file_path),
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return {}
    if process.returncode != 0:
        return {}
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {}


async def get_audio_duration(file_path: Path) -> float:
    """Длительность аудио/видео в секундах."""
    info = await _run_ffprobe(file_path)
    try:
        return float(info.get("format", {}).get("duration", "0"))
    except (ValueError, TypeError):
        return 0.0


def has_audio_stream(info: dict) -> bool:
    """Проверить наличие аудиопотока."""
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio":
            return True
    return False


async def extract_audio_from_video(input_path: Path, output_path: Path) -> Path:
    """Извлечь аудиодорожку из видеофайла в OGG Opus."""
    logger.info(f"Извлечение аудио из видео: {input_path.name}")
    await _run_ffmpeg([
        "-i", str(input_path),
        "-vn",              # Без видео
        "-ar", "48000",
        "-ac", "1",
        "-c:a", "libopus",
        "-b:a", "48k",
        "-threads", "0",   # Все доступные ядра CPU
        str(output_path),
    ], timeout=3600)
    logger.info(f"Аудио извлечено: {output_path.stat().st_size / 1024:.0f} КБ")
    return output_path


async def convert_to_ogg(input_path: Path, output_path: Path) -> Path:
    """Конвертировать аудиофайл в OGG Opus."""
    logger.info(f"Конвертация: {input_path.name} → OGG Opus")
    await _run_ffmpeg([
        "-i", str(input_path),
        "-ar", "48000",
        "-ac", "1",
        "-c:a", "libopus",
        "-b:a", "48k",
        "-threads", "0",
        str(output_path),
    ], timeout=3600)
    logger.info(f"Конвертация завершена: {output_path.stat().st_size / 1024:.0f} КБ")
    return output_path


async def convert_to_wav_16k(input_path: Path, output_path: Path) -> Path:
    """Конвертировать аудио в WAV PCM 16кГц моно (для диаризации)."""
    logger.info(f"Конвертация для диаризации: {input_path.name} → WAV 16кГц")
    await _run_ffmpeg([
        "-i", str(input_path),
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        "-threads", "0",
        str(output_path),
    ], timeout=3600)
    logger.info(f"Готово: {output_path.stat().st_size / 1024:.0f} КБ")
    return output_path


def _round_to_15(seconds: float) -> int:
    """Округлить длительность вверх до кратного 15 секунд."""
    import math
    return max(15, math.ceil(seconds / 15) * 15)


async def split_into_chunks(
    file_path: Path,
    output_dir: Path,
    chunk_sec: int = CHUNK_DURATION_SEC,
) -> List[Tuple[Path, float]]:
    """
    Нарезать аудио на чанки.
    chunk_sec должен быть кратен 15 (для Yandex).
    Используем запас 0.5с чтобы OGG кодек не превысил лимит 30с.
    """
    duration = await get_audio_duration(file_path)

    # Безопасная длина: chunk_sec минус запас на кодек
    safe_length = chunk_sec - 0.5

    chunks = []
    start = 0.0
    idx = 0

    while start < duration:
        remaining = duration - start

        # Пропускаем слишком короткие остатки
        if remaining < 3 and idx > 0:
            break

        length = min(safe_length, remaining)

        chunk_path = output_dir / f"chunk_{idx:04d}.ogg"
        await _run_ffmpeg([
            "-i", str(file_path),
            "-ss", str(start),
            "-t", str(length),
            "-ar", "48000",
            "-ac", "1",
            "-c:a", "libopus",
            "-b:a", "48k",
            str(chunk_path),
        ], timeout=60)

        chunks.append((chunk_path, start))
        logger.info(f"Чанк {idx}: {start:.1f}с — {start + length:.1f}с")

        start += safe_length
        idx += 1

    logger.info(f"Итого чанков: {len(chunks)} (длительность: {duration:.0f}с, шаг: {safe_length}с)")
    return chunks
