"""Yandex SpeechKit — синхронный и асинхронный STT API."""

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Callable, Awaitable, Optional

import httpx

_TRANSIENT = (httpx.ConnectError, httpx.TimeoutException, httpx.ReadTimeout, httpx.RemoteProtocolError)
_MAX_RETRIES = 5

from bot.config import (
    YANDEX_API_KEY, YANDEX_FOLDER_ID,
    YANDEX_S3_BUCKET, YANDEX_S3_KEY_ID, YANDEX_S3_SECRET_KEY,
)
from bot.utils.http import get_client

logger = logging.getLogger(__name__)

# ── Endpoints ──
SYNC_STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
ASYNC_STT_URL = "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
GET_RECOGNITION_URL = "https://stt.api.cloud.yandex.net/stt/v3/getRecognition"
OPERATIONS_URL = "https://operation.api.cloud.yandex.net/operations"
S3_ENDPOINT = "https://storage.yandexcloud.net"


# ══════════════════════════════════════════════════════════════════
# Синхронный API (чанки до 30с / 1МБ)
# ══════════════════════════════════════════════════════════════════

async def transcribe_chunk(file_path: Path, language: str = "ru-RU") -> str:
    """Распознать один аудиочанк через Yandex SpeechKit (sync)."""
    if not YANDEX_API_KEY:
        raise ValueError("YANDEX_API_KEY не задан в .env")
    if not YANDEX_FOLDER_ID:
        raise ValueError("YANDEX_FOLDER_ID не задан в .env")

    if not file_path.exists():
        raise FileNotFoundError(f"Файл чанка не найден: {file_path}")

    with open(file_path, "rb") as f:
        audio_data = f.read()

    file_size = len(audio_data)
    if file_size == 0:
        raise ValueError(f"Файл чанка пустой (0 байт): {file_path}")
    if file_size > 1024 * 1024:
        raise ValueError(f"Файл чанка слишком большой ({file_size} байт > 1 МБ): {file_path}")

    logger.info(f"Yandex STT sync: {file_path.name} ({file_size / 1024:.0f} КБ)")

    params = {
        "folderId": YANDEX_FOLDER_ID,
        "lang": language,
        "format": "oggopus",
        "sampleRateHertz": 48000,
    }
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}

    for attempt in range(_MAX_RETRIES):
        try:
            async with get_client(timeout=60) as client:
                response = await client.post(
                    SYNC_STT_URL, params=params, headers=headers, content=audio_data,
                )
            break
        except _TRANSIENT as e:
            if attempt < _MAX_RETRIES - 1:
                retry_wait = 5 * (attempt + 1)
                logger.warning(f"Sync STT сетевая ошибка (попытка {attempt + 1}/{_MAX_RETRIES}): {e}. Повтор через {retry_wait}с")
                await asyncio.sleep(retry_wait)
            else:
                raise

    if response.status_code != 200:
        error = response.text[:300]
        logger.error(f"Yandex STT ошибка ({response.status_code}): {error}")
        raise Exception(f"Yandex STT ошибка ({response.status_code}): {error}")

    text = response.json().get("result", "")
    logger.debug(f"Распознано: {text[:80]}...")
    return text


# ══════════════════════════════════════════════════════════════════
# Асинхронный API (longRunningRecognize, весь файл целиком)
# ══════════════════════════════════════════════════════════════════

def _s3_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=YANDEX_S3_KEY_ID,
        aws_secret_access_key=YANDEX_S3_SECRET_KEY,
    )


async def _upload_to_s3(file_path: Path, object_key: str) -> str:
    """Загрузить файл в Yandex Object Storage и вернуть URI."""
    loop = asyncio.get_event_loop()

    def _upload():
        _s3_client().upload_file(str(file_path), YANDEX_S3_BUCKET, object_key)

    await loop.run_in_executor(None, _upload)
    return f"{S3_ENDPOINT}/{YANDEX_S3_BUCKET}/{object_key}"


async def _delete_from_s3(object_key: str) -> None:
    """Удалить файл из Yandex Object Storage."""
    loop = asyncio.get_event_loop()

    def _delete():
        _s3_client().delete_object(Bucket=YANDEX_S3_BUCKET, Key=object_key)

    await loop.run_in_executor(None, _delete)


async def _poll_operation(
    operation_id: str,
    headers: dict,
    max_wait: int = 1800,
    on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
) -> None:
    """Опрашивать операцию до завершения. Raises при ошибке или таймауте."""
    url = f"{OPERATIONS_URL}/{operation_id}"
    elapsed = 0
    poll_interval = 10

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        resp = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with get_client(timeout=30) as client:
                    resp = await client.get(url, headers=headers)
                break
            except _TRANSIENT as e:
                if attempt < _MAX_RETRIES - 1:
                    retry_wait = 5 * (attempt + 1)
                    logger.warning(
                        f"Сетевая ошибка при опросе операции (попытка {attempt + 1}/{_MAX_RETRIES}): {e}. "
                        f"Повтор через {retry_wait}с"
                    )
                    await asyncio.sleep(retry_wait)
                else:
                    logger.error(f"Исчерпаны попытки опроса операции {operation_id}: {e}")
                    raise

        if resp.status_code != 200:
            raise Exception(f"Ошибка опроса операции ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        if data.get("done"):
            if "error" in data:
                raise Exception(f"Ошибка распознавания: {data['error']}")
            logger.info(f"STT operation done: {operation_id}")
            return

        if on_progress and elapsed % 30 == 0:
            await on_progress(f"🎙 Распознавание... {elapsed}с")

        logger.debug(f"Operation {operation_id}: ждём ({elapsed}с)")

    raise Exception(f"Таймаут ожидания операции {operation_id} ({max_wait}с)")


async def _fetch_recognition_result(operation_id: str, headers: dict) -> list:
    """
    Получить результаты распознавания через getRecognition endpoint (v3).

    Возвращает список объектов из стримингового JSON-ответа.
    Каждый объект: {"result": {"final": {"alternatives": [...], "channelTag": "0"}, ...}}
    """
    params = {"operationId": operation_id}

    for attempt in range(_MAX_RETRIES):
        try:
            async with get_client(timeout=120) as client:
                resp = await client.get(GET_RECOGNITION_URL, headers=headers, params=params)
            break
        except _TRANSIENT as e:
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(5 * (attempt + 1))
            else:
                raise

    if resp.status_code != 200:
        raise Exception(f"getRecognition ошибка ({resp.status_code}): {resp.text[:300]}")

    raw = resp.text
    logger.info(f"getRecognition raw (первые 500 символов): {raw[:500]}")

    items = []

    # Пробуем JSON-массив
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except json.JSONDecodeError:
        pass

    # NDJSON (каждая строка — отдельный JSON-объект)
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning(f"Не удалось разобрать строку getRecognition: {line[:100]}")

    logger.info(f"getRecognition: разобрано {len(items)} объектов")
    return items


def _parse_recognition_simple(items: list) -> str:
    """Извлечь текст из ответа getRecognition без диаризации."""
    texts = []
    for item in items:
        result = item.get("result", item)  # некоторые форматы без обёртки "result"
        final = result.get("final", {})
        alternatives = final.get("alternatives", [])
        if alternatives:
            text = alternatives[0].get("text", "").strip()
            if text:
                texts.append(text)
    return " ".join(texts)


def _parse_recognition_diarized(items: list) -> str:
    """Извлечь текст с метками говорящих из ответа getRecognition."""
    segments = []
    for item in items:
        result = item.get("result", item)
        final = result.get("final", {})
        alternatives = final.get("alternatives", [])
        if not alternatives:
            continue
        text = alternatives[0].get("text", "").strip()
        if not text:
            continue
        # speakerTag может быть в alternatives[0] или в final или в result
        speaker = (
            alternatives[0].get("speakerTag")
            or final.get("speakerTag")
            or result.get("speakerTag")
            or final.get("channelTag", "0")
        )
        segments.append((str(speaker), text))

    unique_speakers = {s for s, _ in segments}
    logger.info(f"Диаризация: сегментов={len(segments)}, спикеров={unique_speakers}")

    if not segments:
        return _parse_recognition_simple(items)

    lines = []
    current_speaker = None
    current_parts: list[str] = []

    for speaker, text in segments:
        if speaker != current_speaker:
            if current_parts and current_speaker is not None:
                lines.append(f"Участник {current_speaker}: {' '.join(current_parts)}")
            current_speaker = speaker
            current_parts = [text]
        else:
            current_parts.append(text)

    if current_parts and current_speaker is not None:
        lines.append(f"Участник {current_speaker}: {' '.join(current_parts)}")

    return "\n\n".join(lines)


async def async_transcribe_file(
    file_path: Path,
    language: str = "ru-RU",
    with_diarization: bool = False,
    on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
) -> str:
    """
    Распознать аудиофайл через Yandex SpeechKit async API (весь файл, без нарезки).

    with_diarization=True — включает speakerLabels для протокола совещания.
    Ожидает настроенного Yandex Object Storage (YANDEX_S3_*).
    """
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        raise ValueError("Не заданы YANDEX_API_KEY / YANDEX_FOLDER_ID")
    if not all([YANDEX_S3_BUCKET, YANDEX_S3_KEY_ID, YANDEX_S3_SECRET_KEY]):
        raise ValueError("Не заданы параметры Object Storage (YANDEX_S3_BUCKET/KEY_ID/SECRET_KEY)")

    # Определяем формат по расширению (v3 API containerAudio типы)
    ext = file_path.suffix.lower().lstrip(".")
    audio_format_map = {
        "ogg":  {"containerAudio": {"containerAudioType": "OGG_OPUS"}},
        "opus": {"containerAudio": {"containerAudioType": "OGG_OPUS"}},
        "wav":  {"containerAudio": {"containerAudioType": "WAV"}},
        "mp3":  {"containerAudio": {"containerAudioType": "MP3"}},
        "flac": {"containerAudio": {"containerAudioType": "FLAC"}},
    }
    audio_format = audio_format_map.get(ext, {"containerAudio": {"containerAudioType": "OGG_OPUS"}})

    object_key = f"stt/{uuid.uuid4().hex}_{file_path.name}"

    # 1. Загрузка в Object Storage
    file_size_kb = file_path.stat().st_size / 1024 if file_path.exists() else 0
    logger.info(f"Загрузка в S3: {file_path.name} → {object_key} ({file_size_kb:.0f} КБ, формат: {ext})")
    s3_uri = await _upload_to_s3(file_path, object_key)

    try:
        # 2. Запуск асинхронного распознавания (v3 API)
        body = {
            "uri": s3_uri,
            "recognitionModel": {
                "model": "general",
                "audioFormat": audio_format,
                "languageRestriction": {
                    "restrictionType": "WHITELIST",
                    "languageCode": [language],
                },
                "textNormalization": {
                    "textNormalization": "TEXT_NORMALIZATION_ENABLED",
                    "profanityFilter": False,
                    "literatureText": False,
                },
            },
        }
        if with_diarization:
            body["speakerLabeling"] = {"speakerLabeling": "SPEAKER_LABELING_ENABLED"}

        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}",
            "x-folder-id": YANDEX_FOLDER_ID,
        }

        for attempt in range(_MAX_RETRIES):
            try:
                async with get_client(timeout=30) as client:
                    resp = await client.post(ASYNC_STT_URL, json=body, headers=headers)
                break
            except _TRANSIENT as e:
                if attempt < _MAX_RETRIES - 1:
                    retry_wait = 5 * (attempt + 1)
                    logger.warning(f"Async STT сетевая ошибка (попытка {attempt + 1}/{_MAX_RETRIES}): {e}. Повтор через {retry_wait}с")
                    await asyncio.sleep(retry_wait)
                else:
                    raise

        if resp.status_code != 200:
            raise Exception(f"Async STT ошибка ({resp.status_code}): {resp.text[:300]}")

        resp_data = resp.json()
        operation_id = resp_data.get("id")
        if not operation_id:
            raise Exception(f"Не получен operation_id: {resp.text[:300]}")
        logger.info(f"Async STT v3 запрос принят, operation_id: {operation_id}")

        # 3. Ожидание завершения операции
        await _poll_operation(operation_id, headers, on_progress=on_progress)

        # 4. Получение результатов через getRecognition
        logger.info(f"Запрос результатов getRecognition: {operation_id}")
        items = await _fetch_recognition_result(operation_id, headers)

        # 5. Парсинг
        if with_diarization:
            return _parse_recognition_diarized(items)
        else:
            return _parse_recognition_simple(items)

    finally:
        # 6. Удаление из S3
        try:
            await _delete_from_s3(object_key)
            logger.info(f"S3 файл удалён: {object_key}")
        except Exception as e:
            logger.warning(f"Не удалось удалить файл из S3 ({object_key}): {e}")


async def validate_key() -> bool:
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        return False
    try:
        headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}"}
        params = {"folderId": YANDEX_FOLDER_ID, "lang": "ru-RU"}
        async with get_client(timeout=10) as client:
            response = await client.post(SYNC_STT_URL, params=params, headers=headers, content=b"")
        return response.status_code == 400
    except Exception:
        return False
