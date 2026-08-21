"""Команды /start, /help, /menu — MAX версия."""

import logging

from maxapi import Bot, Dispatcher, F
from maxapi.types import MessageCreated, BotStarted, Command, MessageCallback
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton

from bot.config import (
    FREE_TRIAL_MAX_MINUTES, SUBSCRIPTION_PRICE_RUB, SUBSCRIPTION_MINUTES,
    PRICE_PER_MINUTE_RUB, THESES_PRICE_RUB, PROTOCOL_PRICE_RUB, API_PORT,
    MAX_BOT_LINK, REFERRAL_BONUS_MINUTES,
)
from bot.database import (
    ensure_user, add_free_minutes, create_api_key, link_max_account,
    apply_start_payload, get_referral_stats,
)

logger = logging.getLogger(__name__)
HOURS = SUBSCRIPTION_MINUTES // 60


def _welcome_kb():
    kb = InlineKeyboardBuilder()
    kb.add(CallbackButton(text="🎯 Возможности бота", payload="welcome:features"))
    kb.add(CallbackButton(text="💎 Тарифы", payload="welcome:pricing"))
    kb.add(CallbackButton(text="🚀 Начать работу", payload="welcome:start"))
    return kb.adjust(1).as_markup()


async def _invite_text(user_id: int) -> str:
    stats = await get_referral_stats(user_id)
    link = f"{MAX_BOT_LINK}?start=ref{user_id}"
    return (
        f"🤝 Приглашайте коллег — бонус получаете оба!\n\n"
        f"За каждого друга, который запустит бота по вашей ссылке, "
        f"вы и он получите по {REFERRAL_BONUS_MINUTES:.0f} минут расшифровки бесплатно.\n\n"
        f"Ваша ссылка:\n{link}\n\n"
        f"👥 Уже приглашено: {stats['invited_count']}"
    )


async def _process_referral(bot: Bot, user_id: int, is_new: bool, payload: str):
    """При первом /start с deep-link payload — зачислить реферальный бонус или сохранить источник."""
    if not is_new or not payload:
        return
    try:
        referrer_id = await apply_start_payload(user_id, payload)
    except Exception:
        logger.exception("Ошибка обработки start-payload %r для %s", payload, user_id)
        return
    if referrer_id:
        try:
            await bot.send_message(
                chat_id=referrer_id,
                text=(
                    f"🎉 По вашей ссылке присоединился новый пользователь!\n"
                    f"+{REFERRAL_BONUS_MINUTES:.0f} мин начислено на ваш баланс."
                ),
            )
        except Exception:
            logger.warning("Не удалось уведомить реферера %s", referrer_id)


def register_start_handlers(dp: Dispatcher, bot: Bot):

    @dp.bot_started()
    async def on_bot_started(event: BotStarted):
        user_id = event.user.user_id
        username = event.user.username or ""
        is_new = await ensure_user(user_id, username, username)
        await _process_referral(bot, user_id, is_new, event.payload or "")

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
        is_new = await ensure_user(user_id, username, username)

        text = event.message.body.text or ""
        parts = text.strip().split()
        payload = parts[1].strip() if len(parts) > 1 else ""
        await _process_referral(bot, user_id, is_new, payload)

        await event.message.answer(
            f"👋 Привет, {username or 'друг'}!\n\n"
            f"Я — бот для расшифровки аудио и видео.\n"
            f"Превращаю записи совещаний, интервью и конференций "
            f"в текстовые документы Word.\n\n"
            f"🆓 Попробуйте бесплатно — первый файл до {FREE_TRIAL_MAX_MINUTES} мин!\n\n"
            f"Нажмите кнопку ниже или отправьте файл 👇",
            attachments=[_welcome_kb()],
        )

    @dp.message_created(Command("invite"))
    async def cmd_invite(event: MessageCreated):
        user_id = event.message.sender.user_id
        username = event.message.sender.username or ""
        await ensure_user(user_id, username, username)
        await event.message.answer(await _invite_text(user_id))

    @dp.message_callback(F.callback.payload == "menu:invite")
    async def cb_invite(event: MessageCallback):
        user_id = event.callback.user.user_id
        await ensure_user(user_id)
        await event.message.answer(await _invite_text(user_id))

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
            f"/menu /balance /subscribe /topup /invite"
        )

    @dp.message_created(Command("freejune"))
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

    @dp.message_created(Command("apikey"))
    async def cmd_apikey(event: MessageCreated):
        user_id = event.message.sender.user_id
        username = event.message.sender.username or ""
        await ensure_user(user_id, username, username)

        text = event.message.body.text or ""
        parts = text.strip().split(maxsplit=1)
        name = parts[1] if len(parts) > 1 else ""

        key_id, raw_key = await create_api_key(user_id, name)
        await event.message.answer(
            f"🔑 API-ключ создан (показывается один раз!):\n\n"
            f"`{raw_key}`\n\n"
            f"Используйте в заголовке:\n"
            f"`Authorization: Bearer {raw_key}`\n\n"
            f"Документация: http://{{ваш-сервер}}:{API_PORT}/api/docs\n\n"
            f"⚠️ Сохраните ключ — повторно он не отображается.\n"
            f"Чтобы отозвать: /revokekey {key_id}"
        )

    @dp.message_created(Command("revokekey"))
    async def cmd_revokekey(event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text or ""
        parts = text.strip().split()
        if len(parts) < 2 or not parts[1].isdigit():
            await event.message.answer("Использование: /revokekey <id>\nID ключа указан при его создании.")
            return
        from bot.database import revoke_api_key
        ok = await revoke_api_key(int(parts[1]), user_id)
        if ok:
            await event.message.answer(f"✅ Ключ #{parts[1]} отозван.")
        else:
            await event.message.answer("❌ Ключ не найден или уже отозван.")

    @dp.message_created(Command("link"))
    async def cmd_link(event: MessageCreated):
        user_id = event.message.sender.user_id
        username = event.message.sender.username or ""
        await ensure_user(user_id, username, username)

        text = event.message.body.text or ""
        parts = text.strip().split()
        if len(parts) < 2:
            await event.message.answer(
                "Использование: /link КОД\n\n"
                "Получить код можно на сайте летописца в разделе «Привязать MAX»."
            )
            return

        code = parts[1].strip()
        ok = await link_max_account(code, user_id)
        if ok:
            await event.message.answer(
                "✅ Аккаунт MAX успешно привязан к вашему профилю на сайте!\n"
                "Теперь баланс синхронизирован между ботом и сайтом."
            )
        else:
            await event.message.answer(
                "❌ Код не найден или срок его действия истёк.\n"
                "Сгенерируйте новый код на сайте и попробуйте снова."
            )
