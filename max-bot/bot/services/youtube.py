"""Загрузка аудио с YouTube через yt-dlp."""

import asyncio
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_YT_DLP = str(Path(sys.executable).parent / "yt-dlp")
_YT_PATTERN = re.compile(
    r'https?://(?:www\.|m\.)?(?:youtube\.com/watch\?(?:[^\s]*&)*v=|youtu\.be/)([a-zA-Z0-9_-]{11})'
)


def extract_youtube_url(text: str) -> str | None:
    match = _YT_PATTERN.search(text)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    return None


async def get_youtube_title(url: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        _YT_DLP, "--no-download", "--print", "%(title)s",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() or "YouTube видео"


async def download_youtube_audio(url: str, output_base: Path) -> Path:
    """Скачать аудио с YouTube в mp3. output_base — путь без расширения."""
    template = str(output_base) + ".%(ext)s"
    proc = await asyncio.create_subprocess_exec(
        _YT_DLP, "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "-o", template,
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"yt-dlp: {stderr.decode()[:300]}")
    mp3_path = Path(str(output_base) + ".mp3")
    if not mp3_path.exists():
        raise Exception("Аудио файл не был создан после загрузки")
    return mp3_path
