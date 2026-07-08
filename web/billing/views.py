import json
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from billing.models import BotUser, BotSubscription, WebTinkoffOrder
from billing.tinkoff import create_topup_order, verify_notification

logger = logging.getLogger(__name__)

TOPUP_AMOUNTS = [100, 200, 500, 1000]


@login_required
def billing_index(request):
    user = request.user
    bot_user = BotUser.objects.filter(user_id=user.bot_user_id).first() if user.bot_user_id else None
    subscription = None
    if bot_user:
        subscription = BotSubscription.objects.filter(
            user_id=user.bot_user_id, is_active=True, expires_at__gt=timezone.now()
        ).order_by("-expires_at").first()

    recent_orders = WebTinkoffOrder.objects.filter(web_user=user).order_by("-created_at")[:10]

    return render(request, "billing/index.html", {
        "bot_user": bot_user,
        "subscription": subscription,
        "recent_orders": recent_orders,
        "topup_amounts": TOPUP_AMOUNTS,
        "subscription_price": settings.SUBSCRIPTION_PRICE_RUB,
        "subscription_hours": settings.SUBSCRIPTION_MINUTES // 60,
    })


@login_required
@require_POST
def topup(request):
    try:
        amount_rub = int(request.POST.get("amount", 0))
    except (ValueError, TypeError):
        messages.error(request, "Некорректная сумма.")
        return redirect("/billing/")

    if amount_rub < 50:
        messages.error(request, "Минимальная сумма пополнения — 50 ₽.")
        return redirect("/billing/")
    if amount_rub > 50000:
        messages.error(request, "Максимальная сумма пополнения — 50 000 ₽.")
        return redirect("/billing/")

    if not settings.TINKOFF_TERMINAL_KEY:
        messages.error(request, "Оплата временно недоступна.")
        return redirect("/billing/")

    if not request.user.bot_user_id:
        messages.error(request, "Ошибка: аккаунт не инициализирован. Обратитесь в поддержку.")
        return redirect("/billing/")

    try:
        result = create_topup_order(request.user, amount_rub)
        return redirect(result["payment_url"])
    except Exception as e:
        logger.error("Topup error for user %s: %s", request.user.pk, e)
        messages.error(request, f"Ошибка создания платежа: {str(e)[:100]}")
        return redirect("/billing/")


@csrf_exempt
@require_POST
def tinkoff_notify(request):
    """Webhook от T-Bank для веб-платежей."""
    try:
        data = json.loads(request.body)
    except Exception:
        return HttpResponse("BAD REQUEST", status=400)

    logger.info("Web T-Bank notify: status=%s order=%s", data.get("Status"), data.get("OrderId"))

    if not verify_notification(data):
        logger.warning("Web T-Bank notify: неверная подпись")
        return HttpResponse("INVALID TOKEN", status=400)

    if data.get("Status") != "CONFIRMED":
        return HttpResponse("OK")

    order_id = data.get("OrderId", "")
    try:
        order = WebTinkoffOrder.objects.get(order_id=order_id)
    except WebTinkoffOrder.DoesNotExist:
        logger.warning("Web T-Bank notify: заказ не найден: %s", order_id)
        return HttpResponse("OK")

    if order.status == "paid":
        return HttpResponse("OK")

    order.status = "paid"
    order.tinkoff_payment_id = str(data.get("PaymentId", order.tinkoff_payment_id))
    order.save(update_fields=["status", "tinkoff_payment_id"])

    web_user = order.web_user
    if web_user.bot_user_id:
        BotUser.objects.filter(user_id=web_user.bot_user_id).update(
            star_balance=F("star_balance") + order.amount_rub
        )
        logger.info("Web topup: user %s +%d ₽", web_user.pk, order.amount_rub)

    return HttpResponse("OK")


@login_required
def payment_success(request):
    messages.success(request, "Оплата прошла успешно! Баланс будет зачислен в течение минуты.")
    return redirect("/billing/")


@login_required
def payment_fail(request):
    messages.error(request, "Оплата не была завершена. Попробуйте ещё раз.")
    return redirect("/billing/")
