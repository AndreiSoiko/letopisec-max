"""Клиент T-Bank Интернет-эквайринга v2."""

import hashlib
import logging
import uuid

import aiohttp

from bot.config import (
    TINKOFF_TERMINAL_KEY, TINKOFF_PASSWORD, TINKOFF_TAXATION,
    TINKOFF_SUCCESS_URL, TINKOFF_FAIL_URL, TINKOFF_NOTIFICATION_URL,
)

logger = logging.getLogger(__name__)
_API_BASE = "https://securepay.tinkoff.ru/v2"


def _token(params: dict) -> str:
    """SHA-256 от конкатенации значений, отсортированных по ключу.
    Password добавляется; Token и вложенные объекты/массивы исключаются."""
    data = {**params, "Password": TINKOFF_PASSWORD}
    filtered = {
        k: v for k, v in data.items()
        if k != "Token" and not isinstance(v, (dict, list))
    }
    joined = "".join(str(v) for _, v in sorted(filtered.items()))
    return hashlib.sha256(joined.encode()).hexdigest()


def verify_notification(data: dict) -> bool:
    """Проверить подпись входящего уведомления от T-Bank."""
    return data.get("Token") == _token(data)


def new_order_id(user_id: int, kind: str) -> str:
    """Уникальный OrderId вида '12345_topup_a1b2c3d4'."""
    return f"{user_id}_{kind}_{uuid.uuid4().hex[:8]}"


async def init_payment(amount_rub: int, order_id: str, description: str, email: str) -> dict | None:
    """
    POST /v2/Init.
    Возвращает {'payment_id': str, 'payment_url': str} или None при ошибке.
    email — адрес покупателя для фискального чека (обязателен при фискализации).
    """
    amount_kopecks = amount_rub * 100
    params: dict = {
        "TerminalKey": TINKOFF_TERMINAL_KEY,
        "Amount": amount_kopecks,
        "OrderId": order_id,
        "Description": description,
        "Receipt": {
            "Email": email,
            "Taxation": TINKOFF_TAXATION,
            "Items": [{
                "Name": description[:64],
                "Price": amount_kopecks,
                "Quantity": 1.00,
                "Amount": amount_kopecks,
                "Tax": "none",
                "PaymentMethod": "full_prepayment",
                "PaymentObject": "service",
            }],
        },
    }
    if TINKOFF_NOTIFICATION_URL:
        params["NotificationURL"] = TINKOFF_NOTIFICATION_URL
    if TINKOFF_SUCCESS_URL:
        params["SuccessURL"] = TINKOFF_SUCCESS_URL
    if TINKOFF_FAIL_URL:
        params["FailURL"] = TINKOFF_FAIL_URL

    params["Token"] = _token(params)  # Receipt (dict) и Items (list) исключаются автоматически

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{_API_BASE}/Init", json=params) as resp:
                result = await resp.json()
    except Exception as exc:
        logger.error("T-Bank Init ошибка: %s", exc)
        return None

    if not result.get("Success"):
        logger.warning("T-Bank Init неуспешно: %s", result)
        return None

    return {
        "payment_id": str(result["PaymentId"]),
        "payment_url": result["PaymentURL"],
    }


async def get_state(payment_id: str) -> str | None:
    """POST /v2/GetState — статус платежа или None при ошибке."""
    params = {"TerminalKey": TINKOFF_TERMINAL_KEY, "PaymentId": payment_id}
    params["Token"] = _token(params)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{_API_BASE}/GetState", json=params) as resp:
                result = await resp.json()
        return result.get("Status")
    except Exception as exc:
        logger.error("T-Bank GetState ошибка: %s", exc)
        return None
