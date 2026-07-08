import hashlib
import secrets
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from billing.models import BotApiKey


@login_required
def index(request):
    user = request.user
    keys = BotApiKey.objects.filter(user_id=user.bot_user_id).order_by("-created_at") if user.bot_user_id else []
    return render(request, "api_keys/index.html", {"keys": keys})


@login_required
@require_POST
def create_key(request):
    user = request.user
    if not user.bot_user_id:
        messages.error(request, "Аккаунт не инициализирован.")
        return redirect("/api-keys/")

    name = request.POST.get("name", "").strip()[:100]
    raw_key = "lp_" + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    BotApiKey.objects.create(user_id=user.bot_user_id, key_hash=key_hash, name=name)
    # Показываем ключ один раз через сессию
    request.session["new_api_key"] = raw_key
    messages.success(request, "API-ключ создан.")
    return redirect("/api-keys/")


@login_required
@require_POST
def clear_session_key(request):
    request.session.pop("new_api_key", None)
    return HttpResponse("OK")


@login_required
@require_POST
def revoke_key(request, key_id: int):
    user = request.user
    updated = BotApiKey.objects.filter(id=key_id, user_id=user.bot_user_id).update(is_active=False)
    if updated:
        messages.success(request, "Ключ отозван.")
    else:
        messages.error(request, "Ключ не найден.")
    return redirect("/api-keys/")
