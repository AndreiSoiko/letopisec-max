"""Административная панель — секретное меню для аналитики и биллинга."""

import logging
from pathlib import Path

from maxapi import Bot, Dispatcher, F
from maxapi.enums.upload_type import UploadType
from maxapi.types import MessageCreated, MessageCallback
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton

from bot.utils.debug import is_admin
from bot.database import (
    get_overview_stats, get_user_billing,
    get_payments_report, get_usage_report,
    get_tinkoff_order, complete_tinkoff_order,
    add_stars, create_subscription, get_star_balance, save_payment,
)
from bot.services.excel_report import (
    build_overview_report, build_user_billing_report,
    build_payments_report, build_usage_report,
)
from bot.services.tinkoff import get_state
from bot.config import SUBSCRIPTION_MINUTES

logger = logging.getLogger(__name__)

# Администраторы, ожидающие ввода user_id для запроса биллинга
_waiting_user_id: dict[int, bool] = {}


def _admin_menu() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.add(CallbackButton(text="📊 Общая статистика", payload="adm:overview"))
    kb.add(CallbackButton(text="👤 По пользователю", payload="adm:user_prompt"))
    kb.add(CallbackButton(text="💰 Отчёт по платежам", payload="adm:payments"))
    kb.add(CallbackButton(text="📈 Отчёт по использованию", payload="adm:usage"))
    return kb


async def _send_xlsx(bot: Bot, chat_id: int, path: Path, caption: str):
    try:
        from maxapi.types.input_media import InputMedia
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            attachments=[InputMedia(path=str(path), type=UploadType.FILE)],
        )
    finally:
        path.unlink(missing_ok=True)


def register_admin_handlers(dp: Dispatcher, bot: Bot):

    @dp.message_created(F.message.body.text.lower().contains("/admin"))
    async def cmd_admin(event: MessageCreated):
        user_id = event.message.sender.user_id
        if not is_admin(user_id):
            return
        kb = _admin_menu()
        await event.message.answer(
            "🔐 Панель администратора\nВыберите отчёт:",
            attachments=[kb.adjust(1).as_markup()],
        )

    @dp.message_callback(F.callback.payload == "adm:overview")
    async def cb_overview(event: MessageCallback):
        user_id = event.callback.user.user_id
        if not is_admin(user_id):
            return
        chat_id = event.message.recipient.chat_id
        await event.answer("⏳ Формирую отчёт...")
        try:
            stats = await get_overview_stats()
            path = build_overview_report(stats)
            await _send_xlsx(bot, chat_id, path, "📊 Общая статистика")
        except Exception as e:
            logger.exception(f"Ошибка отчёта overview: {e}")
            await bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {str(e)[:200]}")

    @dp.message_callback(F.callback.payload == "adm:payments")
    async def cb_payments(event: MessageCallback):
        user_id = event.callback.user.user_id
        if not is_admin(user_id):
            return
        chat_id = event.message.recipient.chat_id
        await event.answer("⏳ Формирую отчёт...")
        try:
            rows = await get_payments_report()
            path = build_payments_report(rows)
            await _send_xlsx(bot, chat_id, path, f"💰 Платежи — {len(rows)} записей")
        except Exception as e:
            logger.exception(f"Ошибка отчёта payments: {e}")
            await bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {str(e)[:200]}")

    @dp.message_callback(F.callback.payload == "adm:usage")
    async def cb_usage(event: MessageCallback):
        user_id = event.callback.user.user_id
        if not is_admin(user_id):
            return
        chat_id = event.message.recipient.chat_id
        await event.answer("⏳ Формирую отчёт...")
        try:
            rows = await get_usage_report()
            path = build_usage_report(rows)
            await _send_xlsx(bot, chat_id, path, f"📈 Использование — {len(rows)} транскрибаций")
        except Exception as e:
            logger.exception(f"Ошибка отчёта usage: {e}")
            await bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {str(e)[:200]}")

    @dp.message_callback(F.callback.payload == "adm:user_prompt")
    async def cb_user_prompt(event: MessageCallback):
        user_id = event.callback.user.user_id
        if not is_admin(user_id):
            return
        _waiting_user_id[user_id] = True
        await event.answer("👤 Жду user_id...")
        await bot.send_message(
            chat_id=event.message.recipient.chat_id,
            text="👤 Введите user_id пользователя (числовой идентификатор):",
        )

    @dp.message_created(
        F.message.body.text
        & F.message.sender.user_id.func(lambda uid: uid in _waiting_user_id)
    )
    async def handle_admin_text(event: MessageCreated):
        user_id = event.message.sender.user_id
        if not is_admin(user_id):
            return
        text = (event.message.body.text or "").strip()
        if not text or text.startswith("/"):
            return

        _waiting_user_id.pop(user_id, None)
        chat_id = event.message.recipient.chat_id

        if not text.lstrip("-").isdigit():
            await event.message.answer("❌ Неверный формат. user_id должен быть числом.")
            return

        target_id = int(text)
        await event.message.answer(f"⏳ Получаю данные пользователя {target_id}...")
        try:
            data = await get_user_billing(target_id)
            if not data:
                await event.message.answer(f"❌ Пользователь {target_id} не найден в базе.")
                return
            path = build_user_billing_report(data)
            username = data["user"].get("username") or str(target_id)
            await _send_xlsx(bot, chat_id, path, f"👤 Биллинг пользователя @{username} ({target_id})")
        except Exception as e:
            logger.exception(f"Ошибка биллинга пользователя {target_id}: {e}")
            await bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {str(e)[:200]}")

    @dp.message_created(F.message.body.text.lower().contains("/admin_pay"))
    async def cmd_admin_pay(event: MessageCreated):
        user_id = event.message.sender.user_id
        if not is_admin(user_id):
            return

        text = (event.message.body.text or "").strip()
        parts = text.split()
        if len(parts) < 2:
            await event.message.answer(
                "❌ Укажите order_id. Пример:\n/admin_pay 12345678_topup_a1b2c3d4"
            )
            return

        order_id = parts[1].strip()
        await event.message.answer(f"🔍 Проверяю заказ {order_id}...")

        order = await get_tinkoff_order(order_id)
        if not order:
            await event.message.answer(f"❌ Заказ {order_id} не найден в базе данных.")
            return

        if order["status"] == "paid":
            await event.message.answer(f"ℹ️ Заказ {order_id} уже обработан (status=paid).")
            return

        payment_id = order.get("tinkoff_payment_id", "")
        tbank_status = await get_state(payment_id)
        if tbank_status != "CONFIRMED":
            await event.message.answer(
                f"⚠️ T-Bank статус: {tbank_status}. Платёж не подтверждён — зачисление не выполнено."
            )
            return

        await complete_tinkoff_order(order_id)
        target_user_id = order["user_id"]
        payment_type = order["payment_type"]
        amount_rub = order["amount_rub"]

        try:
            await save_payment(
                user_id=target_user_id,
                amount_stars=amount_rub,
                telegram_charge_id=payment_id,
                payload=order_id,
            )
        except Exception as exc:
            logger.error("admin_pay: ошибка сохранения payment: %s", exc)

        if payment_type == "topup":
            await add_stars(target_user_id, amount_rub)
            balance = await get_star_balance(target_user_id)
            await bot.send_message(
                chat_id=target_user_id,
                text=f"✅ Баланс пополнен на {amount_rub} ₽\n💰 Текущий баланс: {balance} ₽",
            )
            await event.message.answer(
                f"✅ Зачислено: +{amount_rub} ₽ пользователю {target_user_id}\n"
                f"💰 Баланс: {balance} ₽"
            )

        elif payment_type == "subscription":
            sub = await create_subscription(
                user_id=target_user_id,
                stars_paid=amount_rub,
                telegram_charge_id=payment_id,
                minutes_total=SUBSCRIPTION_MINUTES,
            )
            exp = sub["expires_at"].strftime("%d.%m.%Y")
            hours = SUBSCRIPTION_MINUTES // 60
            await bot.send_message(
                chat_id=target_user_id,
                text=(
                    f"✅ Подписка активирована!\n"
                    f"📅 Действует до {exp}\n"
                    f"⏱ {hours} часов распознавания\n"
                    f"🎯 Тезисы и протокол включены"
                ),
            )
            await event.message.answer(
                f"✅ Подписка активирована для пользователя {target_user_id} до {exp}"
            )
