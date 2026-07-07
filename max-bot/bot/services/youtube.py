"""Загрузка аудио с YouTube и других медиасервисов через yt-dlp."""

import asyncio
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, quote

import httpx

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
    r'(?:[a-z0-9-]+\.)*vkvideo\.ru/video[^\s]*|'
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
    r'disk\.yandex\.ru/[^\s]+|'
    r'yadi\.sk/[^\s]+|'
    r'disk\.yandex\.com/[^\s]+|'
    r'[^\s]+\.(?:mp3|mp4|wav|ogg|flac|m4a|aac|webm|mkv|avi|mov)(?:[?#][^\s]*)?'
    r')',
    re.IGNORECASE,
)


def is_yandex_disk_url(url: str) -> bool:
    try:
        return urlparse(url).netloc.lower() in ("disk.yandex.ru", "yadi.sk", "disk.yandex.com")
    except Exception:
        return False


async def _yadisk_api(endpoint: str, public_url: str) -> dict:
    """Публичный API Яндекс.Диска, авторизация не требуется."""
    base = "https://cloud-api.yandex.net/v1/disk/public/resources"
    api_url = f"{base}/{endpoint}?public_key={quote(public_url, safe='')}" if endpoint else \
              f"{base}?public_key={quote(public_url, safe='')}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(api_url)
        resp.raise_for_status()
        return resp.json()


async def _download_yadisk_file(public_url: str, output_base: Path) -> Path:
    """Скачать файл с Яндекс.Диска через публичный API."""
    try:
        meta = await _yadisk_api("", public_url)
        file_name = meta.get("name", "yadisk_file")
    except Exception:
        file_name = "yadisk_file"

    try:
        data = await _yadisk_api("download", public_url)
        download_url = data["href"]
    except Exception as e:
        raise Exception(f"Не удалось получить ссылку скачивания с Яндекс.Диска: {e}")

    ext = Path(file_name).suffix.lower() or ".mp3"
    out_path = Path(str(output_base) + ext)
    async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
        async with client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise Exception("Файл с Яндекс.Диска не был скачан или оказался пустым")
    return out_path


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
    """Получает название через yt-dlp или Яндекс.Диск API; fallback — домен из URL."""
    if is_yandex_disk_url(url):
        try:
            meta = await _yadisk_api("", url)
            return meta.get("name", "Яндекс.Диск файл")
        except Exception:
            return "Яндекс.Диск файл"

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
    """Скачать аудио с любого поддерживаемого сервиса в mp3 (или оригинальный формат для Яндекс.Диска)."""
    if is_yandex_disk_url(url):
        return await _download_yadisk_file(url, output_base)

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
