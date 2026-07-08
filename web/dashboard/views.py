from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from billing.models import BotUser, BotSubscription, BotApiJob


@login_required
def index(request):
    user = request.user
    bot_user = BotUser.objects.filter(user_id=user.bot_user_id).first() if user.bot_user_id else None
    subscription = None
    if bot_user:
        subscription = BotSubscription.objects.filter(
            user_id=user.bot_user_id, is_active=True, expires_at__gt=timezone.now()
        ).order_by("-expires_at").first()

    recent_jobs = []
    if user.bot_user_id:
        recent_jobs = list(BotApiJob.objects.filter(user_id=user.bot_user_id).order_by("-created_at")[:5])

    sub_remaining = None
    if subscription:
        sub_remaining = round(subscription.minutes_total - subscription.minutes_used)

    return render(request, "dashboard/index.html", {
        "bot_user": bot_user,
        "subscription": subscription,
        "sub_remaining": sub_remaining,
        "recent_jobs": recent_jobs,
    })
