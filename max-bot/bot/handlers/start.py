"""Команды /start, /help, /menu — MAX версия."""

import logging

from maxapi import Bot, Dispatcher, F
from maxapi.types import MessageCreated, BotStarted, Command, MessageCallback
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton

from bot.config import (
    FREE_TRIAL_MAX_MINUTES, SUBSCRIPTION_PRICE_RUB, SUBSCRIPTION_MINUTES,
    PRICE_PER_MINUTE_RUB, THESES_PRICE_RUB, PROTOCOL_PRICE_RUB,
)
from bot.database import ensure_user, add_free_minutes

logger = logging.getLogger(__name__)
HOURS = SUBSCRIPTION_MINUTES // 60


def _welcome_kb():
    kb = InlineKeyboardBuilder()
    kb.add(CallbackButton(text="🎯 Возможности бота", payload="welcome:features"))
    kb.add(CallbackButton(text="💎 Тарифы", payload="welcome:pricing"))
    kb.add(CallbackButton(text="🚀 Начать работу", payload="welcome:start"))
    return kb.adjust(1).as_markup()


def register_start_handlers(dp: Dispatcher, bot: Bot):

    @dp.bot_started()
    async def on_bot_started(event: BotStarted):
        user_id = event.user.user_id
        username = event.user.username or ""
        await ensure_user(user_id, username, username)

        await event.bot.send_message(
            chat_id=event.chat_id,
            text=(
                f"👋 Привет, {username or 'друг'}!\n\n"
                f"Я — бот для расшифровки аудио и видео.\n"
                f"Превращаю записи совещаний, интервью и конференций "
                f"в текстовые документы Word.\n\n"
                f"🆓 Попробуйте бесплатно — первый файл до {FREE_TRIAL_MAX_MINUTES} мин!\n\n"
                f"Нажмите кнопку ниже или просто отправьте файл 👇"
            ),
            attachments=[_welcome_kb()],
        )

    @dp.message_created(Command("start"))
    async def cmd_start(event: MessageCreated):
        user_id = event.message.sender.user_id
        username = event.message.sender.username or ""
        await ensure_user(user_id, username, username)

        await event.message.answer(
            f"👋 Привет, {username or 'друг'}!\n\n"
            f"Я — бот для расшифровки аудио и видео.\n"
            f"Превращаю записи совещаний, интервью и конференций "
            f"в текстовые документы Word.\n\n"
            f"🆓 Попробуйте бесплатно — первый файл до {FREE_TRIAL_MAX_MINUTES} мин!\n\n"
            f"Нажмите кнопку ниже или отправьте файл 👇",
            attachments=[_welcome_kb()],
        )

    @dp.message_callback(F.callback.payload == "welcome:features")
    async def cb_features(event: MessageCallback):
        await event.answer(
            "🎯 Что умеет бот\n\n"
            "📝 Распознавание речи — Yandex SpeechKit, 6 языков\n"
            "🧠 AI-коррекция ошибок\n"
            "🎯 Ключевые тезисы\n"
            "📋 Протокол совещания — решения, задачи, сроки\n"
            "🎬 Видео: Zoom, Teams, Skype, Телемост\n"
            "🌐 RU, EN, DE, FR, ES, TR\n"
            "📄 Результат — Word (.docx)"
        )

    @dp.message_callback(F.callback.payload == "welcome:pricing")
    async def cb_pricing(event: MessageCallback):
        await event.answer(
            f"💎 Тарифы\n\n"
            f"🆓 Пробный: 1 файл до {FREE_TRIAL_MAX_MINUTES} мин — бесплатно\n\n"
            f"💎 Подписка — {SUBSCRIPTION_PRICE_RUB} ₽/мес\n"
            f"• {HOURS} часов, тезисы и протокол бесплатно\n\n"
            f"⏱ Поминутно — {PRICE_PER_MINUTE_RUB} ₽/мин\n"
            f"• Тезисы: +{THESES_PRICE_RUB} ₽\n"
            f"• Протокол: +{PROTOCOL_PRICE_RUB} ₽\n\n"
            f"Оплата: Тинькофф / СБП"
        )

    @dp.message_callback(F.callback.payload == "welcome:start")
    async def cb_start_work(event: MessageCallback):
        await event.answer(
            "🚀 Готов к работе!\n\n"
            "1️⃣ Отправьте аудио или видео\n"
            "2️⃣ Выберите язык\n"
            "3️⃣ Выберите операцию\n"
            "4️⃣ Получите Word-документ\n\n"
            "/menu — управление | /help — справка"
        )

    @dp.message_created(Command("help"))
    async def cmd_help(event: MessageCreated):
        await event.message.answer(
            "📖 Справка\n\n"
            "Отправьте файл → язык → операция → документ\n\n"
            f"📝 Распознавание\n"
            f"📝+🎯 +Тезисы (+{THESES_PRICE_RUB} ₽)\n"
            f"📝+📋 +Протокол (+{PROTOCOL_PRICE_RUB} ₽)\n"
            f"(по подписке — бесплатно)\n\n"
            f"Форматы: MP3 WAV OGG FLAC M4A MP4 MKV AVI MOV WebM\n\n"
            f"/menu /balance /subscribe /topup"
        )

    @dp.message_created(Command("promofree"))
    async def cmd_promofree(event: MessageCreated):
        user_id = event.message.sender.user_id
        username = event.message.sender.username or ""
        await ensure_user(user_id, username, username)

        text = event.message.body.text or ""
        parts = text.strip().split()
        if len(parts) < 2:
            await event.message.answer("Укажите количество минут: /promofree 30")
            return
        try:
            minutes = float(parts[1])
            if minutes <= 0:
                raise ValueError
        except ValueError:
            await event.message.answer("Некорректное количество минут.")
            return

        await add_free_minutes(user_id, minutes)
        await event.message.answer(f"✅ Добавлено {int(minutes)} мин к пробному балансу.")
