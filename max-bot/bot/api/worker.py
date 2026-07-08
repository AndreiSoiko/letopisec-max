"""Фоновая обработка API-заданий (транскрибация, анализ)."""

import asyncio
import logging
from pathlib import Path

import httpx

from bot.config import (
    YANDEX_API_KEY, YANDEX_S3_BUCKET, YANDEX_S3_KEY_ID, YANDEX_S3_SECRET_KEY,
    THESES_PRICE_RUB, PROTOCOL_PRICE_RUB, SUPPORTED_VIDEO_FORMATS,
)
from bot.database import (
    check_access, set_trial_used, add_minutes_used, save_transcription,
    deduct_stars, deduct_free_minutes, update_api_job,
)
from bot.services.audio import (
    get_audio_duration, convert_to_ogg, extract_audio_from_video,
    split_into_chunks, convert_to_wav_16k,
)
from bot.services.yandex_stt import transcribe_chunk, async_transcribe_file
from bot.services.correction import correct_transcription
from bot.services.theses import extract_theses
from bot.services.protocol import extract_protocol
from bot.services.custom import process_with_custom_prompt
from bot.services.speakers import identify_speakers, apply_speaker_names
from bot.services.translation import translate_text, TRANSLATE_LANG_NAMES
from bot.services.youtube import download_audio_from_url, is_yandex_disk_url
from bot.utils.helpers import get_temp_path, cleanup_user_files, format_duration

logger = logging.getLogger(__name__)

_ANALYSIS_LABELS = {
    "theses": "КЛЮЧЕВЫЕ ТЕЗИСЫ",
    "protocol": "ПРОТОКОЛ СОВЕЩАНИЯ",
    "custom": "РЕЗУЛЬТАТ ОБРАБОТКИ",
}


async def process_job(job_id: str, user_id: int, info: dict):
    """Запускается как asyncio-задача. Обрабатывает задание и пишет результат в БД."""
    await update_api_job(job_id, status="processing")

    mode = info["mode"]
    file_url = info["file_url"]
    language = info.get("language", "ru-RU")
    translate_to = info.get("translate_to", "") or ""
    custom_prompt = info.get("custom_prompt", "") or ""

    with_theses = mode == "theses"
    with_protocol = mode == "protocol"
    with_custom = mode == "custom"
    with_translate = mode == "translate"

    try:
        # 1. Скачивание
        input_path = get_temp_path(user_id, "api_input")
        if is_yandex_disk_url(file_url):
            input_path = await download_audio_from_url(file_url, input_path)
        else:
            ext = file_url.split("?")[0].rsplit(".", 1)[-1].lower()
            input_path = Path(str(input_path) + f".{ext}")
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
                resp = await client.get(file_url)
                resp.raise_for_status()
                input_path.write_bytes(resp.content)

        if not input_path.exists() or input_path.stat().st_size == 0:
            raise ValueError("Файл не скачался или пустой")

        # 2. Аудио
        ext = input_path.suffix.lower().lstrip(".")
        is_video = ext in SUPPORTED_VIDEO_FORMATS
        if is_video:
            ogg_path = get_temp_path(user_id, "api_extracted.ogg")
            await extract_audio_from_video(input_path, ogg_path)
        else:
            ogg_path = get_temp_path(user_id, "api_converted.ogg")
            await convert_to_ogg(input_path, ogg_path)

        # 3. Длительность + доступ
        duration_sec = await get_audio_duration(ogg_path)
        duration_min = duration_sec / 60

        extra_cost = 0
        access = await check_access(user_id, duration_sec)
        if access.get("reason") == "pay_per_minute":
            if with_theses:
                extra_cost = THESES_PRICE_RUB
            elif with_protocol:
                extra_cost = PROTOCOL_PRICE_RUB

        if not access["allowed"]:
            reason = access["reason"]
            if reason == "trial_too_long":
                msg = f"Файл слишком длинный ({format_duration(duration_sec)}). Бесплатно до {access.get('max_minutes')} мин."
            elif reason == "no_access":
                cost = access.get("cost", 0) + extra_cost
                msg = f"Недостаточно средств. Стоимость: {cost} ₽, баланс: {access.get('balance', 0)} ₽"
            else:
                msg = "Нет доступа к транскрибации"
            raise PermissionError(msg)

        cost = access.get("cost_stars", 0) + extra_cost
        if cost > 0:
            ok = await deduct_stars(user_id, cost)
            if not ok:
                raise PermissionError("Не удалось списать средства — недостаточно баланса")

        # 4. Транскрибация
        use_async = bool(YANDEX_S3_BUCKET and YANDEX_S3_KEY_ID and YANDEX_S3_SECRET_KEY)

        if use_async:
            stt_path = ogg_path
            if with_protocol:
                wav_path = get_temp_path(user_id, "api_diarize.wav")
                await convert_to_wav_16k(input_path, wav_path)
                stt_path = wav_path
            full_text = await async_transcribe_file(
                stt_path, language=language, with_diarization=with_protocol,
            )
        else:
            chunks_dir = get_temp_path(user_id, "api_chunks")
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunks = await split_into_chunks(ogg_path, chunks_dir)
            all_texts = []
            for idx, (chunk_path, chunk_start) in enumerate(chunks):
                try:
                    text = await transcribe_chunk(chunk_path, language=language)
                    if text.strip():
                        if chunk_start > 0:
                            text = f"[{format_duration(chunk_start)}] {text}"
                        all_texts.append(text)
                except Exception as e:
                    logger.error("API job %s chunk %d: %s", job_id, idx, e)
                await asyncio.sleep(0.3)
            full_text = "\n\n".join(all_texts)

        if not full_text.strip():
            raise ValueError("Не удалось распознать речь — возможно неверный язык или тишина")

        # 4.5. Имена спикеров (только протокол + диаризация)
        if with_protocol and use_async and YANDEX_API_KEY:
            try:
                speaker_mapping = await identify_speakers(full_text)
                if speaker_mapping:
                    full_text = apply_speaker_names(full_text, speaker_mapping)
            except Exception as e:
                logger.error("API job %s speakers: %s", job_id, e)

        # 5. Коррекция
        if YANDEX_API_KEY and not with_protocol and not with_translate:
            try:
                full_text = await correct_transcription(full_text)
            except Exception as e:
                logger.error("API job %s correction: %s", job_id, e)

        # 6. Анализ
        analysis_text = ""
        analysis_label = ""
        if YANDEX_API_KEY:
            if with_theses:
                analysis_text = await extract_theses(full_text)
                analysis_label = _ANALYSIS_LABELS["theses"]
            elif with_protocol:
                analysis_text = await extract_protocol(full_text)
                analysis_label = _ANALYSIS_LABELS["protocol"]
            elif with_custom and custom_prompt:
                analysis_text = await process_with_custom_prompt(full_text, custom_prompt)
                analysis_label = _ANALYSIS_LABELS["custom"]
            elif with_translate and translate_to:
                analysis_text = await translate_text(full_text, translate_to)
                lang_label = TRANSLATE_LANG_NAMES.get(translate_to, translate_to)
                analysis_label = f"ПЕРЕВОД НА {lang_label.upper()}"

        # 7. Учёт
        is_trial = access.get("is_trial", False)
        if is_trial:
            await set_trial_used(user_id)
        elif access["reason"] == "free_minutes":
            await deduct_free_minutes(user_id, duration_min)
        elif access["reason"] == "subscription":
            await add_minutes_used(user_id, duration_min)

        await save_transcription(
            user_id=user_id, file_name=file_url.split("/")[-1][:100],
            duration_sec=duration_sec, stars_spent=cost,
            is_trial=is_trial, with_theses=with_theses or with_protocol,
            mode=mode,
        )

        # 8. Сохранение результата
        await update_api_job(
            job_id,
            status="done",
            duration_sec=duration_sec,
            result_text=full_text,
            result_analysis=analysis_text or None,
        )
        # analysis_label сохраним в result_analysis с префиксом если нужно
        if analysis_text and analysis_label:
            await update_api_job(
                job_id,
                status="done",
                result_analysis=f"{analysis_label}\n\n{analysis_text}",
            )

    except Exception as e:
        logger.exception("API job %s failed: %s", job_id, e)
        await update_api_job(job_id, status="error", error=str(e)[:500])
    finally:
        cleanup_user_files(user_id)
