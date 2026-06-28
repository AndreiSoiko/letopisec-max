"""Загрузка аудио с YouTube и других медиасервисов через yt-dlp."""

import asyncio
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_YT_DLP = str(Path(sys.executable).parent / "yt-dlp")

_YT_PATTERN = re.compile(
    r'https?://(?:www\.|m\.)?(?:youtube\.com/watch\?(?:[^\s]*&)*v=|youtu\.be/)([a-zA-Z0-9_-]{11})'
)

# Паттерн для медиа-ссылок: известные видеохостинги + прямые ссылки на аудио/видеофайлы
_MEDIA_URL_RE = re.compile(
    r'https?://(?:www\.|m\.)?(?:'
    r'(?:youtube\.com/(?:watch|shorts|live|embed)|youtu\.be/)[^\s]*|'
    r'vk\.com/video[^\s]*|'
    r'rutube\.ru/video/[^\s]*|'
    r'ok\.ru/video[^\s]*|'
    r'dzen\.ru/video/[^\s]*|'
    r'vimeo\.com/\d[^\s]*|'
    r'(?:www\.)?tiktok\.com/@[^\s]*/video/[^\s]*|'
    r'twitch\.tv/videos/[^\s]*|'
    r'clips\.twitch\.tv/[^\s]*|'
    r'instagram\.com/(?:reel|p|tv)/[^\s]*|'
    r'dailymotion\.com/video/[^\s]*|'
    r'coub\.com/view/[^\s]*|'
    r'[^\s]+\.(?:mp3|mp4|wav|ogg|flac|m4a|aac|webm|mkv|avi|mov)(?:[?#][^\s]*)?'
    r')',
    re.IGNORECASE,
)


def extract_youtube_url(text: str) -> str | None:
    match = _YT_PATTERN.search(text)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    return None


def extract_media_url(text: str) -> str | None:
    """Извлекает URL медиаконтента (видеохостинги + прямые ссылки на файлы)."""
    m = _MEDIA_URL_RE.search(text)
    return m.group(0).rstrip(".,)\"'") if m else None


async def get_youtube_title(url: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        _YT_DLP, "--no-download", "--print", "%(title)s",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() or "YouTube видео"


async def get_media_title(url: str) -> str:
    """Получает название через yt-dlp; fallback — домен из URL."""
    proc = await asyncio.create_subprocess_exec(
        _YT_DLP, "--no-download", "--print", "%(title)s",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    title = stdout.decode().strip()
    if not title or title.upper().startswith("ERROR") or title.startswith("["):
        try:
            title = urlparse(url).netloc or "Видео по ссылке"
        except Exception:
            title = "Видео по ссылке"
    return title


async def download_youtube_audio(url: str, output_base: Path) -> Path:
    """Скачать аудио с YouTube в mp3. output_base — путь без расширения."""
    return await download_audio_from_url(url, output_base)


async def download_audio_from_url(url: str, output_base: Path) -> Path:
    """Скачать аудио с любого поддерживаемого сервиса в mp3."""
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
        err = stderr.decode()[:400]
        raise Exception(f"yt-dlp: {err}")
    mp3_path = Path(str(output_base) + ".mp3")
    if not mp3_path.exists():
        raise Exception("Аудио файл не был создан после загрузки")
    return mp3_path
