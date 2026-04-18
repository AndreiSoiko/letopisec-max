"""Обработчик аудио/видео — пайплайн транскрибации (MAX версия)."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from maxapi import Bot, Dispatcher, F
from maxapi.enums.upload_type import UploadType
from maxapi.types import MessageCreated, MessageCallback
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.filters.filter import BaseFilter

from bot.config import (
    ALL_SUPPORTED_FORMATS, SUPPORTED_VIDEO_FORMATS,
    OPENROUTER_API_KEY, FREE_TRIAL_MAX_MINUTES,
    SUBSCRIPTION_PRICE_RUB, PRICE_PER_MINUTE_RUB,
    THESES_PRICE_RUB, PROTOCOL_PRICE_RUB,
    MAX_FILE_SIZE_BYTES,
    YANDEX_S3_BUCKET, YANDEX_S3_KEY_ID, YANDEX_S3_SECRET_KEY,
)
from bot.utils.helpers import (
    get_temp_path, cleanup_user_files, format_duration,
    format_file_size, get_file_extension, rate_limiter,
)
from bot.utils.debug import is_admin, create_error_report, get_first_admin
from bot.database import (
    ensure_user, check_access, set_trial_used,
    add_minutes_used, save_transcription, deduct_stars,
    deduct_free_minutes,
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
from bot.services.docx_builder import build_docx
from bot.services.speakers import identify_speakers, apply_speaker_names
from bot.handlers.payment import _menu_kb

logger = logging.getLogger(__name__)

MAX_EXTRA_PROCESSINGS = 8

LANG_NAMES = {
    "ru-RU": "🇷🇺 Русский", "en-US": "🇬🇧 English",
    "de-DE": "🇩🇪 Deutsch", "fr-FR": "🇫🇷 Français",
    "es-ES": "🇪🇸 Español", "tr-TR": "🇹🇷 Türkçe",
}

# Файлы, ожидающие выбора операции
_pending_files: dict[int, dict] = {}
# Распознанный текст для повторной обработки без переотправки файла
_processed_results: dict[int, dict] = {}
# Пользователи, ожидающие ввода своего промта: {user_id: {"type": "initial"|"extra"}}
_waiting_custom_prompt: dict[int, dict] = {}


class _WaitingPromptFilter(BaseFilter):
    async def __call__(self, event) -> bool:
        return event.message.sender.user_id in _waiting_custom_prompt


def _has_media(event: MessageCreated) -> bool:
    if not event.message.body or not event.message.body.attachments:
        return False
    for att in event.message.body.attachments:
        if getattr(att, "type", "") in ("audio", "video", "file"):
            return True
    return False


def _build_initial_ops_keyboard(lang: str) -> InlineKeyboardBuilder:
    label = LANG_NAMES.get(lang, lang)
    kb = InlineKeyboardBuilder()
    kb.add(CallbackButton(text="📝 Распознавание", payload="op:transcribe"))
    kb.add(CallbackButton(text=f"📝+🎯 +Тезисы (+{THESES_PRICE_RUB} ₽)", payload="op:theses"))
    kb.add(CallbackButton(text=f"📝+📋 +Протокол (+{PROTOCOL_PRICE_RUB} ₽)", payload="op:protocol"))
    kb.add(CallbackButton(text="✏️ Свой вариант", payload="op:custom"))
    kb.add(CallbackButton(text=f"🌐 Сменить язык ({label})", payload="op:back_lang"))
    kb.add(CallbackButton(text="❌ Отмена", payload="op:cancel"))
    return kb


def _build_extra_ops_keyboard(extra_count: int) -> InlineKeyboardBuilder:
    remaining = MAX_EXTRA_PROCESSINGS - extra_count
    kb = InlineKeyboardBuilder()
    kb.add(CallbackButton(text="🎯 Тезисы", payload="extra:theses"))
    kb.add(CallbackButton(text="📋 Протокол", payload="extra:protocol"))
    kb.add(CallbackButton(text="✏️ Свой вариант", payload="extra:custom"))
    kb.add(CallbackButton(text="❌ Завершить", payload="extra:finish"))
    return kb


def register_transcribe_handlers(dp: Dispatcher, bot: Bot):

    @dp.message_created(F.message.body.text.lower().contains('test'))
    async def test(event: MessageCreated):
        await event.message.answer('Тест')

    @dp.message_created(F.message.body.attachments)
    async def handle_media(event: MessageCreated):
        if not _has_media(event):
            return

        user_id = event.message.sender.user_id
        username = event.message.sender.username or ""
        await ensure_user(user_id, username, username)

        if not rate_limiter.is_allowed(user_id):
            await event.message.answer("⏳ Подождите минуту.")
            return

        attachment = None
        for att in event.message.body.attachments:
            if getattr(att, "type", "") in ("audio", "video", "file"):
                attachment = att
                break
        if not attachment:
            return

        att_type = getattr(attachment, "type", "file")

        # File: filename/size — прямо на attachment; url — в payload
        # Audio: url — в payload, filename/size отсутствуют
        # Video: urls — объект с разрешениями, filename/size отсутствуют
        file_name = (
            getattr(attachment, "filename", None)
            or getattr(attachment.payload, "filename", None)
            or "file"
        )
        file_size = (
            getattr(attachment, "size", None)
            or getattr(attachment.payload, "size", None)
            or 0
        )
        if att_type == "video":
            urls = getattr(attachment, "urls", None)
            file_url = None
            if urls:
                file_url = (
                    urls.mp4_1080 or urls.mp4_720 or urls.mp4_480
                    or urls.mp4_360 or urls.mp4_240 or urls.mp4_144
                )
        else:
            file_url = getattr(attachment.payload, "url", None)

        is_video = att_type == "video" or get_file_extension(file_name) in SUPPORTED_VIDEO_FORMATS

        if not attachment:
            await event.message.answer("❌ Не удалось получить файл.")
            return

        if file_size and file_size > MAX_FILE_SIZE_BYTES:
            await event.message.answer(f"❌ Файл слишком большой: {format_file_size(file_size)}.")
            return

        ext = get_file_extension(file_name)
        if ext and ext not in ALL_SUPPORTED_FORMATS:
            await event.message.answer(
                f"❌ Формат .{ext} не поддерживается.\n"
                f"Аудио: mp3, wav, ogg, flac, m4a, aac, opus\n"
                f"Видео: mp4, mkv, avi, mov, wmv, 3gp"
            )
            return
        _pending_files[user_id] = {
            "file_url": file_url,
            "file_name": file_name,
            "file_size": file_size,
            "is_video": is_video,
            "chat_id": event.message.recipient.chat_id,
            "language": "ru-RU",
        }

        file_type = "🎬 Видео" if is_video else "🎙 Аудио"
        kb = _build_initial_ops_keyboard("ru-RU")
        await event.message.answer(
            f"{file_type} получен: {file_name}\n"
            f"📦 {format_file_size(file_size)}\n\n"
            f"🌐 Язык: 🇷🇺 Русский\n"
            f"Выберите операцию:",
            attachments=[kb.adjust(1).as_markup()],
        )

    # ── Выбор языка ──

    @dp.message_callback(F.callback.payload.startswith("lang:"))
    async def cb_language(event: MessageCallback):
        lang = event.callback.payload.split(":")[1]
        user_id = event.callback.user.user_id
        pending = _pending_files.get(user_id)
        if not pending:
            await event.answer("❌ Файл не найден. Отправьте заново.")
            return
        pending["language"] = lang
        label = LANG_NAMES.get(lang, lang)
        kb = _build_initial_ops_keyboard(lang)
        await event.message.answer(
            f"🌐 Язык: {label}\nВыберите операцию:",
            attachments=[kb.adjust(1).as_markup()],
        )

    @dp.message_callback(F.callback.payload == "op:back_lang")
    async def cb_back_lang(event: MessageCallback):
        user_id = event.callback.user.user_id
        if not _pending_files.get(user_id):
            await event.answer("❌ Файл не найден. Отправьте заново.")
            return
        kb = InlineKeyboardBuilder()
        kb.row(
            CallbackButton(text="🇷🇺 Русский", payload="lang:ru-RU"),
            CallbackButton(text="🇬🇧 English", payload="lang:en-US"),
        )
        kb.row(
            CallbackButton(text="🇩🇪 Deutsch", payload="lang:de-DE"),
            CallbackButton(text="🇫🇷 Français", payload="lang:fr-FR"),
        )
        kb.row(
            CallbackButton(text="🇪🇸 Español", payload="lang:es-ES"),
            CallbackButton(text="🇹🇷 Türkçe", payload="lang:tr-TR"),
        )
        kb.add(CallbackButton(text="❌ Отмена", payload="op:cancel"))
        await event.message.answer(
            "🌐 Выберите язык аудио:",
            attachments=[kb.as_markup()],
        )

    # ── Отмена ──

    @dp.message_callback(F.callback.payload == "op:cancel")
    async def cb_cancel(event: MessageCallback):
        user_id = event.callback.user.user_id
        _pending_files.pop(user_id, None)
        _waiting_custom_prompt.pop(user_id, None)
        await event.message.answer("❌ Отменено. Отправьте файл заново, чтобы начать.")

    # ── Первичная обработка ──

    @dp.message_callback(F.callback.payload == "op:transcribe")
    async def cb_op_transcribe(event: MessageCallback):
        await _start(event, "transcribe")

    @dp.message_callback(F.callback.payload == "op:theses")
    async def cb_op_theses(event: MessageCallback):
        await _start(event, "theses")

    @dp.message_callback(F.callback.payload == "op:protocol")
    async def cb_op_protocol(event: MessageCallback):
        await _start(event, "protocol")

    @dp.message_callback(F.callback.payload == "op:custom")
    async def cb_op_custom(event: MessageCallback):
        user_id = event.callback.user.user_id
        pending = _pending_files.get(user_id)
        if not pending:
            await event.answer("❌ Файл не найден. Отправьте заново.")
            return
        _waiting_custom_prompt[user_id] = {"type": "initial"}
        await event.answer("✏️ Жду ваш промт...")
        await bot.send_message(
            chat_id=pending["chat_id"],
            text=(
                "✏️ Напишите свой способ обработки результатов распознавания файла.\n\n"
                "Например: «Составь частное техническое задание на основе интервью с пользователями»"
            ),
        )

    # ── Дополнительная обработка (без переотправки файла) ──

    @dp.message_callback(F.callback.payload == "extra:theses")
    async def cb_extra_theses(event: MessageCallback):
        await _start_extra(event, "theses")

    @dp.message_callback(F.callback.payload == "extra:protocol")
    async def cb_extra_protocol(event: MessageCallback):
        await _start_extra(event, "protocol")

    @dp.message_callback(F.callback.payload == "extra:custom")
    async def cb_extra_custom(event: MessageCallback):
        user_id = event.callback.user.user_id
        result = _processed_results.get(user_id)
        if not result:
            await event.answer("❌ Данные не найдены. Отправьте файл заново.")
            return
        _waiting_custom_prompt[user_id] = {"type": "extra"}
        await event.answer("✏️ Жду ваш промт...")
        await bot.send_message(
            chat_id=result["chat_id"],
            text=(
                "✏️ Напишите свой способ обработки результатов распознавания файла.\n\n"
                "Например: «Составь частное техническое задание на основе интервью с пользователями»"
            ),
        )

    @dp.message_callback(F.callback.payload == "extra:finish")
    async def cb_extra_finish(event: MessageCallback):
        user_id = event.callback.user.user_id
        _processed_results.pop(user_id, None)
        _waiting_custom_prompt.pop(user_id, None)
        await event.message.answer(
            "Для начала распознавания отправьте аудио или видео файл в чат",
            attachments=[_menu_kb()],
        )

    # ── Приём пользовательского промта ──

    @dp.message_created(F.message.body.text, _WaitingPromptFilter())
    async def handle_text(event: MessageCreated):
        user_id = event.message.sender.user_id
        text = (event.message.body.text or "").strip()
        if not text or text.startswith("/"):
            return
        state = _waiting_custom_prompt.pop(user_id)

        if state["type"] == "initial":
            pending = _pending_files.pop(user_id, None)
            if not pending:
                await event.message.answer("❌ Файл не найден. Отправьте заново.")
                return
            pending["custom_prompt"] = text
            await event.message.answer("⏳ Начинаю обработку...")
            await _process_file(user_id, pending, "custom")
        elif state["type"] == "extra":
            result = _processed_results.get(user_id)
            if not result:
                await event.message.answer("❌ Данные не найдены. Отправьте файл заново.")
                return
            await event.message.answer("⏳ Обрабатываю...")
            await _extra_process(user_id, result, "custom", text)

    # ── Внутренние функции ──

    async def _start(event: MessageCallback, mode: str):
        user_id = event.callback.user.user_id
        pending = _pending_files.pop(user_id, None)
        if not pending:
            await event.answer("❌ Файл не найден. Отправьте заново.")
            return
        await event.answer("⏳ Начинаю обработку...")
        await _process_file(user_id, pending, mode)

    async def _start_extra(event: MessageCallback, mode: str):
        user_id = event.callback.user.user_id
        result = _processed_results.get(user_id)
        if not result:
            await event.answer("❌ Данные не найдены. Отправьте файл заново.")
            return
        await event.answer("⏳ Обрабатываю...")
        await _extra_process(user_id, result, mode)

    async def _extra_process(user_id: int, result: dict, mode: str, custom_prompt: str = ""):
        """Применить операцию к уже распознанному тексту без повторной транскрибации."""
        full_text = result["full_text"]
        file_name = result["file_name"]
        duration_str = result["duration_str"]
        chat_id = result["chat_id"]
        correction_applied = result.get("correction_applied", False)

        async def send(text):
            await bot.send_message(chat_id=chat_id, text=text)

        try:
            analysis_text = ""
            analysis_label = ""
            label_short = ""

            if mode == "theses":
                await send("🎯 Извлекаю тезисы...")
                analysis_text = await extract_theses(full_text)
                analysis_label = "КЛЮЧЕВЫЕ ТЕЗИСЫ"
                label_short = "Тезисы"
            elif mode == "protocol":
                await send("📋 Составляю протокол...")
                analysis_text = await extract_protocol(full_text)
                analysis_label = "ПРОТОКОЛ СОВЕЩАНИЯ"
                label_short = "Протокол"
            elif mode == "custom" and custom_prompt:
                await send("✏️ Применяю ваш промт...")
                analysis_text = await process_with_custom_prompt(full_text, custom_prompt)
                analysis_label = "РЕЗУЛЬТАТ ОБРАБОТКИ"
                label_short = "Свой_вариант"

            if not analysis_text:
                await send("⚠️ Не удалось выполнить обработку.")
                return

            await send("📄 Создание документа...")
            date_str = datetime.now().strftime("%Y-%m-%d")
            safe = "".join(c for c in Path(file_name).stem if c.isalnum() or c in "._- ")[:50]
            docx_filename = f"{label_short}_{safe}_{date_str}.docx"
            docx_path = get_temp_path(user_id, docx_filename)

            final_text = f"{analysis_label}\n\n{analysis_text}\n\n{'─' * 50}\n\nТРАНСКРИБАЦИЯ\n\n{full_text}"
            build_docx(
                text=final_text, output_path=docx_path,
                duration=duration_str, original_filename=file_name,
                correction_applied=correction_applied,
            )

            await send(f"✅ {analysis_label}: готово!")
            try:
                from maxapi.types.input_media import InputMedia
                await bot.send_message(
                    chat_id=chat_id,
                    text="📄 Документ:",
                    attachments=[InputMedia(path=str(docx_path), type=UploadType.FILE)],
                )
            except Exception as e:
                logger.error(f"Отправка файла: {e}")
                await send(f"⚠️ Не удалось отправить файл: {str(e)[:100]}")

            docx_path.unlink(missing_ok=True)

            result["extra_count"] += 1
            extra_count = result["extra_count"]

            if extra_count < MAX_EXTRA_PROCESSINGS:
                remaining = MAX_EXTRA_PROCESSINGS - extra_count
                kb = _build_extra_ops_keyboard(extra_count)
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"🔄 Хотите ещё раз обработать этот файл?\nОсталось попыток: {remaining} из {MAX_EXTRA_PROCESSINGS}",
                    attachments=[kb.adjust(1).as_markup()],
                )
            else:
                _processed_results.pop(user_id, None)
                await send(f"✅ Использовано все {MAX_EXTRA_PROCESSINGS} дополнительных обработок.")
                await bot.send_message(
                    chat_id=chat_id,
                    text="Для начала распознавания отправьте аудио или видео файл в чат",
                    attachments=[_menu_kb()],
                )

        except Exception as e:
            logger.exception(f"Ошибка доп. обработки: {e}")
            await send(f"❌ Ошибка: {str(e)[:200]}")

    async def _process_file(user_id: int, info: dict, mode: str):
        file_url = info["file_url"]
        file_name = info["file_name"]
        file_size = info["file_size"]
        is_video = info["is_video"]
        language = info.get("language", "ru-RU")
        chat_id = info["chat_id"]
        custom_prompt = info.get("custom_prompt", "")
        with_theses = mode == "theses"
        with_protocol = mode == "protocol"
        with_custom = mode == "custom"

        async def send(text):
            await bot.send_message(chat_id=chat_id, text=text)

        speaker_mapping: dict = {}
        try:
            await send(f"⏳ Загружаю файл: {file_name}...")

            # 1. Скачивание
            import httpx
            input_path = get_temp_path(user_id, file_name)
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
                resp = await client.get(file_url)
                resp.raise_for_status()
                with open(input_path, "wb") as f:
                    f.write(resp.content)

            if not input_path.exists() or input_path.stat().st_size == 0:
                raise Exception("Файл не скачался или пустой")
            logger.info(f"Скачано: {input_path} ({input_path.stat().st_size} байт)")

            # 2. Аудио
            if is_video:
                await send("🎬 Извлекаю аудио из видео...")
                ogg_path = get_temp_path(user_id, "extracted.ogg")
                await extract_audio_from_video(input_path, ogg_path)
            else:
                await send("⏳ Конвертация...")
                ogg_path = get_temp_path(user_id, "converted.ogg")
                await convert_to_ogg(input_path, ogg_path)

            # 3. Длительность
            duration_sec = await get_audio_duration(ogg_path)
            duration_str = format_duration(duration_sec)
            duration_min = duration_sec / 60

            # 4. Доступ
            access = await check_access(user_id, duration_sec)

            extra_cost = 0
            if access.get("reason") == "pay_per_minute":
                if with_theses:
                    extra_cost = THESES_PRICE_RUB
                elif with_protocol:
                    extra_cost = PROTOCOL_PRICE_RUB

            if not access["allowed"]:
                reason = access["reason"]
                if reason == "trial_too_long":
                    await send(
                        f"❌ Файл слишком длинный ({duration_str}).\n"
                        f"Бесплатно до {FREE_TRIAL_MAX_MINUTES} мин.\n/subscribe /topup"
                    )
                elif reason == "no_access":
                    cost = access.get("cost", 0) + extra_cost
                    balance = access.get("balance", 0)
                    await send(
                        f"❌ Недостаточно средств.\n"
                        f"Стоимость: {cost} ₽ | Баланс: {balance} ₽\n/topup /subscribe"
                    )
                else:
                    await send("❌ Нет доступа. /menu")
                cleanup_user_files(user_id)
                return

            is_trial = access.get("is_trial", False)
            cost = access.get("cost_stars", 0) + extra_cost

            if cost > 0:
                ok = await deduct_stars(user_id, cost)
                if not ok:
                    await send("❌ Не удалось списать средства. /topup")
                    cleanup_user_files(user_id)
                    return

            # 5. Распознавание
            use_async = bool(YANDEX_S3_BUCKET and YANDEX_S3_KEY_ID and YANDEX_S3_SECRET_KEY)
            errors = 0
            total = 1

            if use_async:
                stt_path = ogg_path
                if with_protocol:
                    await send("⏳ Подготовка аудио для диаризации...")
                    wav_path = get_temp_path(user_id, "diarize.wav")
                    await convert_to_wav_16k(input_path, wav_path)
                    stt_path = wav_path

                await send(f"☁️ Загрузка в облако... ({duration_str})")
                full_text = await async_transcribe_file(
                    stt_path,
                    language=language,
                    with_diarization=with_protocol,
                    on_progress=send,
                )
            else:
                await send(f"⏳ Нарезка ({duration_str})...")
                chunks_dir = get_temp_path(user_id, "chunks")
                chunks_dir.mkdir(parents=True, exist_ok=True)
                chunks = await split_into_chunks(ogg_path, chunks_dir)
                total = len(chunks)

                await send(f"🎙 Распознавание... Чанков: {total}")
                all_texts = []

                for idx, (chunk_path, chunk_start) in enumerate(chunks):
                    try:
                        if not chunk_path.exists() or chunk_path.stat().st_size == 0:
                            raise ValueError(f"Чанк пустой: {chunk_path}")
                        text = await transcribe_chunk(chunk_path, language=language)
                        if text.strip():
                            if chunk_start > 0:
                                ts = format_duration(chunk_start)
                                text = f"[{ts}] {text}"
                            all_texts.append(text)
                    except Exception as e:
                        logger.error(f"Ошибка чанка {idx}: {e}")
                        errors += 1

                    if (idx + 1) % 10 == 0:
                        pct = int((idx + 1) / total * 100)
                        await send(f"🎙 Распознавание: {pct}% ({idx + 1}/{total})")
                    await asyncio.sleep(0.3)

                full_text = "\n\n".join(all_texts)

            if not full_text.strip():
                await send(
                    f"⚠️ Не удалось распознать речь.\n"
                    f"Язык: {language} | Ошибок: {errors}/{total}\n"
                    f"Возможно неверный язык или тишина."
                )
                cleanup_user_files(user_id)
                return

            # 5.5. Идентификация спикеров по именам (только при диаризации)
            if with_protocol and use_async and OPENROUTER_API_KEY:
                await send("🎤 Определяю имена участников...")
                try:
                    speaker_mapping = await identify_speakers(full_text)
                    if speaker_mapping:
                        full_text = apply_speaker_names(full_text, speaker_mapping)
                        logger.info(f"Имена спикеров применены: {speaker_mapping}")
                except Exception as e:
                    logger.error(f"Идентификация спикеров: {e}")

            # 6. Коррекция (пропускается для протокола — LLM удаляет метки спикеров)
            correction_applied = False
            if OPENROUTER_API_KEY and not with_protocol:
                await send("🧠 AI-коррекция...")
                try:
                    full_text = await correct_transcription(full_text)
                    correction_applied = True
                except Exception as e:
                    logger.error(f"Коррекция: {e}")

            # 7. Анализ
            analysis_text = ""
            analysis_label = ""
            if OPENROUTER_API_KEY:
                if with_theses:
                    await send("🎯 Тезисы...")
                    try:
                        analysis_text = await extract_theses(full_text)
                        analysis_label = "КЛЮЧЕВЫЕ ТЕЗИСЫ"
                    except Exception as e:
                        logger.error(f"Тезисы: {e}")
                elif with_protocol:
                    await send("📋 Протокол...")
                    try:
                        analysis_text = await extract_protocol(full_text)
                        analysis_label = "ПРОТОКОЛ СОВЕЩАНИЯ"
                    except Exception as e:
                        logger.error(f"Протокол: {e}")
                elif with_custom and custom_prompt:
                    await send("✏️ Применяю ваш промт...")
                    try:
                        analysis_text = await process_with_custom_prompt(full_text, custom_prompt)
                        analysis_label = "РЕЗУЛЬТАТ ОБРАБОТКИ"
                    except Exception as e:
                        logger.error(f"Пользовательский промт: {e}")

            # 8. DOCX
            await send("📄 Создание документа...")
            date_str = datetime.now().strftime("%Y-%m-%d")
            safe = "".join(c for c in Path(file_name).stem if c.isalnum() or c in "._- ")[:50]
            docx_filename = f"Транскрибация_{safe}_{date_str}.docx"
            docx_path = get_temp_path(user_id, docx_filename)

            final_text = full_text
            if analysis_text:
                final_text = f"{analysis_label}\n\n{analysis_text}\n\n{'─' * 50}\n\nТРАНСКРИБАЦИЯ\n\n{full_text}"

            build_docx(
                text=final_text, output_path=docx_path,
                duration=duration_str, original_filename=file_name,
                correction_applied=correction_applied,
            )

            # 9. Отправка результата
            summary = ["✅ Готово!\n", f"📁 {file_name}"]
            if use_async:
                summary.append(f"⏱ {duration_str}")
            else:
                summary.append(f"⏱ {duration_str} | Чанков: {total - errors}/{total}")
            if is_video:
                summary.append("🎬 Видео → текст")
            if use_async:
                summary.append("☁️ Async STT: ✅")
            if correction_applied:
                summary.append("🧠 AI-коррекция: ✅")
            if analysis_text and with_theses:
                summary.append("🎯 Тезисы: ✅")
            if analysis_text and with_protocol:
                label = "📋 Протокол + 🎤 диаризация: ✅" if use_async else "📋 Протокол: ✅"
                summary.append(label)
            if speaker_mapping:
                names = ", ".join(speaker_mapping.values())
                summary.append(f"🎤 Участники: {names}")
            if analysis_text and with_custom:
                summary.append("✏️ Свой вариант: ✅")
            if cost > 0:
                summary.append(f"💰 Списано: {cost} ₽")
            if is_trial:
                summary.append("\n🆓 Это был бесплатный файл.\n/subscribe — подписка")

            await send("\n".join(summary))

            try:
                from maxapi.types.input_media import InputMedia
                await bot.send_message(
                    chat_id=chat_id,
                    text="📄 Документ:",
                    attachments=[InputMedia(path=str(docx_path), type=UploadType.FILE)],
                )
            except Exception as e:
                logger.error(f"Отправка файла: {e}")
                await send(f"⚠️ Не удалось отправить файл: {str(e)[:100]}")

            # 10. Учёт
            if is_trial:
                await set_trial_used(user_id)
            elif access["reason"] == "free_minutes":
                await deduct_free_minutes(user_id, duration_min)
            elif access["reason"] == "subscription":
                await add_minutes_used(user_id, duration_min)

            await save_transcription(
                user_id=user_id, file_name=file_name,
                duration_sec=duration_sec, stars_spent=cost,
                is_trial=is_trial, with_theses=with_theses or with_protocol,
                mode=mode,
            )

            # 11. Сохранение текста для повторной обработки
            _processed_results[user_id] = {
                "full_text": full_text,
                "file_name": file_name,
                "duration_str": duration_str,
                "chat_id": chat_id,
                "extra_count": 0,
                "correction_applied": correction_applied,
            }
            kb = _build_extra_ops_keyboard(0)
            await bot.send_message(
                chat_id=chat_id,
                text=f"🔄 Хотите ещё раз обработать этот файл?\nДоступно {MAX_EXTRA_PROCESSINGS} дополнительных обработок:",
                attachments=[kb.adjust(1).as_markup()],
            )

        except Exception as e:
            logger.exception(f"Ошибка: {e}")
            await send(f"❌ Ошибка: {str(e)[:200]}")

            admin_id = get_first_admin()
            if admin_id:
                try:
                    report_path = await create_error_report(user_id, file_name, e)
                    await bot.send_message(
                        chat_id=admin_id,
                        text=f"🚨 Ошибка у {user_id}\n📁 {file_name}\n❌ {str(e)[:200]}",
                    )
                    report_path.unlink(missing_ok=True)
                except Exception:
                    pass

        finally:
            cleanup_user_files(user_id)
