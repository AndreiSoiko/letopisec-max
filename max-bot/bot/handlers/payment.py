"""Платежи — подписка, пополнение баланса, меню (MAX версия)."""

import logging
import re

from maxapi import Bot, Dispatcher, F
from maxapi.types import MessageCreated, MessageCallback, Command
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.filters.filter import BaseFilter

from bot.config import (
    SUBSCRIPTION_PRICE_RUB, SUBSCRIPTION_MINUTES,
    FREE_TRIAL_MAX_MINUTES, PRICE_PER_MINUTE_RUB,
    TOPUP_AMOUNTS_RUB, THESES_PRICE_RUB, PROTOCOL_PRICE_RUB,
    TINKOFF_TERMINAL_KEY,
)
from bot.database import (
    ensure_user, get_user, get_active_subscription,
    get_star_balance, get_user_stats, add_stars,
    create_tinkoff_order, save_user_email,
)
from bot.services.tinkoff import init_payment, new_order_id

logger = logging.getLogger(__name__)
HOURS = SUBSCRIPTION_MINUTES // 60

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Состояние ожидания email: user_id → {"type": "topup"|"subscription", "amount": int, "chat_id": int}
_pending_payment: dict[int, dict] = {}
_waiting_email: set[int] = set()


class _WaitingEmailFilter(BaseFilter):
    async def __call__(self, event) -> bool:
        return event.message.sender.user_id in _waiting_email


def _menu_kb():
    kb = InlineKeyboardBuilder()
    kb.add(CallbackButton(text="📄 Баланс и статистика", payload="menu:balance"))
    kb.add(CallbackButton(text="💎 Купить подписку", payload="menu:subscribe"))
    kb.add(CallbackButton(text="💳 Пополнить баланс", payload="menu:topup"))
    kb.add(CallbackButton(text="📖 Тарифы", payload="menu:tariffs"))
    kb.add(CallbackButton(text="🆘 Поддержка", payload="menu:support"))
    return kb.adjust(1).as_markup()


def _topup_amounts_kb():
    kb = InlineKeyboardBuilder()
    for amount in TOPUP_AMOUNTS_RUB:
        kb.add(CallbackButton(text=f"💳 {amount} ₽", payload=f"topup:{amount}"))
    kb.add(CallbackButton(text="⬅️ Меню", payload="menu:back"))
    return kb.adjust(1).as_markup()


def register_payment_handlers(dp: Dispatcher, bot: Bot):

    @dp.message_created(Command("menu"))
    async def cmd_menu(event: MessageCreated):
        await ensure_user(event.message.sender.user_id)
        await event.message.answer("📋 Главное меню", attachments=[_menu_kb()])

    # ── Баланс ──
    @dp.message_created(Command("balance"))
    async def cmd_balance(event: MessageCreated):
        user_id = event.message.sender.user_id
        await ensure_user(user_id)
        user = await get_user(user_id)
        sub = await get_active_subscription(user_id)
        balance = user.get("star_balance", 0)

        lines = [f"📊 Ваш аккаунт\n💰 Баланс: {balance} ₽"]
        if not user["trial_used"]:
            lines.append(f"🆓 Пробный: доступен (до {FREE_TRIAL_MAX_MINUTES} мин)")
        else:
            lines.append("🆓 Пробный: использован")
        if sub:
            remaining = sub["minutes_total"] - sub["minutes_used"]
            lines.append(f"💎 Подписка до {sub['expires_at'].strftime('%d.%m.%Y')} | {remaining:.0f} мин")
        else:
            lines.append("💎 Подписка: нет")

        kb = InlineKeyboardBuilder()
        kb.add(CallbackButton(text="⬅️ Меню", payload="menu:back"))
        await event.message.answer("\n".join(lines), attachments=[kb.as_markup()])

    @dp.message_callback(F.callback.payload == "menu:balance")
    async def cb_balance(event: MessageCallback):
        user_id = event.callback.user.user_id
        await ensure_user(user_id)
        user = await get_user(user_id)
        sub = await get_active_subscription(user_id)
        stats = await get_user_stats(user_id)
        balance = user.get("star_balance", 0)

        lines = [f"📊 Ваш аккаунт\n💰 Баланс: {balance} ₽"]
        if not user["trial_used"]:
            lines.append(f"🆓 Пробный: доступен")
        if sub:
            remaining = sub["minutes_total"] - sub["minutes_used"]
            lines.append(f"💎 Подписка до {sub['expires_at'].strftime('%d.%m.%Y')} | {remaining:.0f} мин")
        else:
            lines.append("💎 Подписка: нет")
        if stats["transcriptions"] > 0:
            lines.append(f"📈 Файлов: {stats['transcriptions']} | Потрачено: {stats['total_stars_spent']} ₽")

        await event.message.answer("\n".join(lines))

    # ── Подписка ──
    @dp.message_created(Command("subscribe"))
    async def cmd_subscribe(event: MessageCreated):
        user_id = event.message.sender.user_id
        chat_id = event.message.recipient.chat_id
        await ensure_user(user_id)
        await _request_or_pay(user_id, chat_id, "subscription", SUBSCRIPTION_PRICE_RUB)

    @dp.message_callback(F.callback.payload == "menu:subscribe")
    async def cb_subscribe(event: MessageCallback):
        user_id = event.callback.user.user_id
        chat_id = event.message.recipient.chat_id
        await ensure_user(user_id)
        await _request_or_pay(user_id, chat_id, "subscription", SUBSCRIPTION_PRICE_RUB)

    # ── Пополнение ──
    @dp.message_created(Command("topup"))
    async def cmd_topup(event: MessageCreated):
        await ensure_user(event.message.sender.user_id)
        await event.message.answer(
            f"💳 Пополнение баланса\n"
            f"Стоимость распознавания: {PRICE_PER_MINUTE_RUB} ₽/мин\n\n"
            f"Выберите сумму:",
            attachments=[_topup_amounts_kb()],
        )

    @dp.message_callback(F.callback.payload == "menu:topup")
    async def cb_topup(event: MessageCallback):
        await ensure_user(event.callback.user.user_id)
        await event.message.answer(
            f"💳 Пополнение баланса\n"
            f"Стоимость: {PRICE_PER_MINUTE_RUB} ₽/мин\n\n"
            f"Выберите сумму:",
            attachments=[_topup_amounts_kb()],
        )

    @dp.message_callback(F.callback.payload.startswith("topup:"))
    async def cb_topup_amount(event: MessageCallback):
        raw = event.callback.payload.split(":")[1]
        if not raw.isdigit():
            await event.answer("❌ Неверная сумма.")
            return
        amount = int(raw)
        user_id = event.callback.user.user_id
        chat_id = event.message.recipient.chat_id
        await _request_or_pay(user_id, chat_id, "topup", amount)

    # ── Приём email ──
    @dp.message_created(F.message.body.text, _WaitingEmailFilter())
    async def handle_email_input(event: MessageCreated):
        user_id = event.message.sender.user_id
        text = (event.message.body.text or "").strip()
        if text.startswith("/"):
            return

        if not _EMAIL_RE.match(text):
            await event.message.answer(
                "❌ Неверный формат email. Введите адрес вида name@example.com:"
            )
            return

        _waiting_email.discard(user_id)
        await save_user_email(user_id, text)

        pending = _pending_payment.pop(user_id, None)
        if pending:
            await _execute_payment(
                user_id=user_id,
                chat_id=pending["chat_id"],
                payment_type=pending["type"],
                amount=pending["amount"],
                email=text,
            )
        else:
            await bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text="✅ Email сохранён. Повторите выбор оплаты.",
            )

    # ── Тестовое пополнение ──
    @dp.message_created(Command("test_topup"))
    async def cmd_test_topup(event: MessageCreated):
        user_id = event.message.sender.user_id
        text = event.message.body.text or ""
        parts = text.split()
        amount = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 100

        await add_stars(user_id, amount)
        balance = await get_star_balance(user_id)
        await event.message.answer(
            f"✅ Тестовое пополнение: +{amount} ₽\n💰 Баланс: {balance} ₽"
        )

    # ── Тарифы ──
    @dp.message_callback(F.callback.payload == "menu:tariffs")
    async def cb_tariffs(event: MessageCallback):
        await event.message.answer(
            f"📖 Тарифы\n\n"
            f"🆓 Пробный: 1 файл до {FREE_TRIAL_MAX_MINUTES} мин — бесплатно\n\n"
            f"💎 Подписка: {SUBSCRIPTION_PRICE_RUB} ₽/мес — {HOURS}ч\n"
            f"   Тезисы и протокол бесплатно\n\n"
            f"⏱ Поминутно: {PRICE_PER_MINUTE_RUB} ₽/мин\n"
            f"   Тезисы: +{THESES_PRICE_RUB} ₽\n"
            f"   Протокол: +{PROTOCOL_PRICE_RUB} ₽"
        )

    # ── Поддержка ──
    @dp.message_callback(F.callback.payload == "menu:support")
    async def cb_support(event: MessageCallback):
        user_id = event.callback.user.user_id
        await event.message.answer(
            "🆘 Поддержка\n\n"
            "📧 Контакты тех. поддержки: letopisec-max@yandex.ru\n"
            f"При обращении укажите свой ID в MAX: {user_id}\n\n"
            "📋 Команды:\n"
            "/menu — главное меню\n"
            "/balance — баланс\n"
            "/topup — пополнить баланс\n"
            "/subscribe — купить подписку"
        )

    # ── Назад ──
    @dp.message_callback(F.callback.payload == "menu:back")
    async def cb_back(event: MessageCallback):
        await event.message.answer("📋 Главное меню", attachments=[_menu_kb()])

    # ── Внутренние функции ──

    async def _request_or_pay(user_id: int, chat_id: int, payment_type: str, amount: int):
        """Проверить наличие email. Если есть — платить, если нет — запросить."""
        if not TINKOFF_TERMINAL_KEY:
            desc = f"подписка на 1 месяц" if payment_type == "subscription" else f"пополнение на {amount} ₽"
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Оплата временно недоступна. Обратитесь в поддержку.",
            )
            return

        user = await get_user(user_id)
        email = user.get("email") if user else None

        if email:
            await _execute_payment(user_id, chat_id, payment_type, amount, email)
        else:
            _pending_payment[user_id] = {
                "type": payment_type,
                "amount": amount,
                "chat_id": chat_id,
            }
            _waiting_email.add(user_id)
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "📧 Для оплаты необходим email — он будет указан в фискальном чеке.\n\n"
                    "Введите ваш email:"
                ),
            )

    async def _execute_payment(user_id: int, chat_id: int, payment_type: str, amount: int, email: str):
        """Создать заказ в T-Bank и отправить ссылку на оплату."""
        if payment_type == "subscription":
            description = f"Летописец: подписка на 1 месяц | MAX ID: {user_id}"
        else:
            description = f"Летописец: пополнение баланса на {amount} ₽ | MAX ID: {user_id}"

        order_id = new_order_id(user_id, payment_type)
        result = await init_payment(
            amount_rub=amount,
            order_id=order_id,
            description=description,
            email=email,
        )

        if not result:
            await bot.send_message(chat_id=chat_id, text="❌ Ошибка создания платежа. Попробуйте позже.")
            return

        await create_tinkoff_order(
            order_id=order_id,
            user_id=user_id,
            chat_id=chat_id,
            payment_type=payment_type,
            amount_rub=amount,
            tinkoff_payment_id=result["payment_id"],
        )

        if payment_type == "subscription":
            text = (
                f"💎 Подписка — {SUBSCRIPTION_PRICE_RUB} ₽/мес\n"
                f"• {HOURS} часов распознавания\n"
                f"• Тезисы и протокол — бесплатно\n\n"
                f"Ссылка для оплаты:\n{result['payment_url']}\n\n"
                f"После оплаты подписка активируется автоматически."
            )
        else:
            text = (
                f"💳 Счёт на {amount} ₽ создан!\n\n"
                f"Ссылка для оплаты:\n{result['payment_url']}\n\n"
                f"После оплаты баланс пополнится автоматически."
            )

        await bot.send_message(chat_id=chat_id, text=text)
