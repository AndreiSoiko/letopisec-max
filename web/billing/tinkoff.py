"""T-Bank (Тинькофф) Интернет-эквайринг для веб-сайта."""
import hashlib
import uuid
import requests
from django.conf import settings

TINKOFF_API_URL = "https://securepay.tinkoff.ru/v2"


def _sign(params: dict) -> str:
    filtered = {k: v for k, v in params.items() if k not in ("Token", "DATA", "Receipt") and v is not None}
    filtered["Password"] = settings.TINKOFF_PASSWORD
    sorted_str = "".join(str(filtered[k]) for k in sorted(filtered))
    return hashlib.sha256(sorted_str.encode()).hexdigest()


def verify_notification(data: dict) -> bool:
    token = data.get("Token", "")
    params = {k: v for k, v in data.items() if k not in ("Token", "DATA", "Receipt") and v is not None}
    params["Password"] = settings.TINKOFF_PASSWORD
    sorted_str = "".join(str(params[k]) for k in sorted(params))
    expected = hashlib.sha256(sorted_str.encode()).hexdigest()
    return token == expected


def create_topup_order(web_user, amount_rub: int, success_url: str = "", fail_url: str = "") -> dict:
    """Создать заказ пополнения баланса. Возвращает {'order_id', 'payment_url', 'payment_id'}."""
    from billing.models import WebTinkoffOrder

    order_id = f"web-topup-{web_user.pk}-{uuid.uuid4().hex[:8]}"
    amount_kopecks = amount_rub * 100

    params = {
        "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
        "Amount": amount_kopecks,
        "OrderId": order_id,
        "Description": f"Пополнение баланса на {amount_rub} ₽",
        "NotificationURL": settings.TINKOFF_WEB_NOTIFICATION_URL,
        "SuccessURL": success_url or settings.TINKOFF_SUCCESS_URL,
        "FailURL": fail_url or settings.TINKOFF_FAIL_URL,
    }
    params["Token"] = _sign(params)

    resp = requests.post(f"{TINKOFF_API_URL}/Init", json=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("Success"):
        raise ValueError(f"T-Bank Init failed: {data.get('Message', 'Unknown error')}")

    WebTinkoffOrder.objects.create(
        order_id=order_id,
        web_user=web_user,
        payment_type="topup",
        amount_rub=amount_rub,
        tinkoff_payment_id=str(data.get("PaymentId", "")),
    )

    return {
        "order_id": order_id,
        "payment_url": data["PaymentURL"],
        "payment_id": data.get("PaymentId"),
    }
