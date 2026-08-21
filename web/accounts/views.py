import secrets
import requests as req
from django.conf import settings
from django.contrib import messages, auth
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone

from accounts.forms import LoginForm, RegisterForm, ChangePasswordForm
from accounts.models import WebUser


# ── Email/Password ──

def register(request):
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        user = WebUser.objects.create_user(
            email=cd["email"],
            password=cd["password1"],
            display_name=cd["display_name"],
        )
        user.initialize_bot_user()
        auth.login(request, user, backend="accounts.backends.EmailBackend")
        messages.success(request, "Добро пожаловать! Аккаунт создан.")
        return redirect("/")
    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    next_url = request.GET.get("next", "/")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        user = auth.authenticate(request, email=cd["email"], password=cd["password"])
        if user:
            auth.login(request, user)
            return redirect(next_url)
        messages.error(request, "Неверный email или пароль.")
    return render(request, "accounts/login.html", {"form": form, "next": next_url})


def logout_view(request):
    auth.logout(request)
    return redirect("/accounts/login/")


@login_required
def change_password(request):
    form = ChangePasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        if not request.user.check_password(cd["old_password"]):
            form.add_error("old_password", "Текущий пароль неверен.")
        else:
            request.user.set_password(cd["new_password1"])
            request.user.save()
            auth.update_session_auth_hash(request, request.user)
            messages.success(request, "Пароль успешно изменён.")
            return redirect("/accounts/profile/")
    return render(request, "accounts/change_password.html", {"form": form})


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


# ── VK OAuth ──

def vk_login(request):
    if not settings.VK_APP_ID:
        messages.error(request, "VK OAuth не настроен. Укажите VK_APP_ID в .env")
        return redirect("/accounts/login/")
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    redirect_uri = request.build_absolute_uri("/accounts/vk/callback/")
    url = (
        f"https://oauth.vk.ru/authorize"
        f"?client_id={settings.VK_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=email"
        f"&response_type=code"
        f"&state={state}"
        f"&v=5.131"
    )
    return redirect(url)


def vk_callback(request):
    if request.GET.get("state") != request.session.pop("oauth_state", None):
        messages.error(request, "Ошибка авторизации VK (неверный state).")
        return redirect("/accounts/login/")
    code = request.GET.get("code")
    if not code:
        messages.error(request, "VK не вернул код авторизации.")
        return redirect("/accounts/login/")

    redirect_uri = request.build_absolute_uri("/accounts/vk/callback/")
    try:
        resp = req.get("https://oauth.vk.ru/access_token", params={
            "client_id": settings.VK_APP_ID,
            "client_secret": settings.VK_APP_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        }, timeout=10)
        data = resp.json()
    except Exception:
        messages.error(request, "Ошибка при обмене кода VK на токен.")
        return redirect("/accounts/login/")

    vk_id = data.get("user_id")
    email = data.get("email", "")
    if not vk_id:
        messages.error(request, "VK не вернул user_id.")
        return redirect("/accounts/login/")

    return _social_login(request, "vk", vk_id, email)


# ── Yandex OAuth ──

def yandex_login(request):
    if not settings.YANDEX_CLIENT_ID:
        messages.error(request, "Yandex OAuth не настроен. Укажите YANDEX_CLIENT_ID в .env")
        return redirect("/accounts/login/")
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    redirect_uri = request.build_absolute_uri("/accounts/yandex/callback/")
    url = (
        f"https://oauth.yandex.ru/authorize"
        f"?response_type=code"
        f"&client_id={settings.YANDEX_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return redirect(url)


def yandex_callback(request):
    if request.GET.get("state") != request.session.pop("oauth_state", None):
        messages.error(request, "Ошибка авторизации Яндекс (неверный state).")
        return redirect("/accounts/login/")
    code = request.GET.get("code")
    if not code:
        messages.error(request, "Яндекс не вернул код авторизации.")
        return redirect("/accounts/login/")

    redirect_uri = request.build_absolute_uri("/accounts/yandex/callback/")
    try:
        token_resp = req.post("https://oauth.yandex.ru/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.YANDEX_CLIENT_ID,
            "client_secret": settings.YANDEX_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
        }, timeout=10)
        token_data = token_resp.json()
        access_token = token_data["access_token"]
        info_resp = req.get("https://login.yandex.ru/info", headers={"Authorization": f"OAuth {access_token}"}, timeout=10)
        info = info_resp.json()
    except Exception:
        messages.error(request, "Ошибка при авторизации через Яндекс.")
        return redirect("/accounts/login/")

    yandex_id = str(info.get("id", ""))
    email = info.get("default_email", "")
    if not yandex_id:
        messages.error(request, "Яндекс не вернул ID пользователя.")
        return redirect("/accounts/login/")

    return _social_login(request, "yandex", yandex_id, email)


def _social_login(request, provider: str, social_id, email: str):
    """Найти или создать пользователя по social_id."""
    if request.user.is_authenticated:
        user = request.user
        if provider == "vk":
            if WebUser.objects.filter(vk_id=social_id).exclude(pk=user.pk).exists():
                messages.error(request, "Этот VK аккаунт уже привязан к другому аккаунту.")
                return redirect("/accounts/profile/")
            user.vk_id = social_id
        else:
            if WebUser.objects.filter(yandex_id=social_id).exclude(pk=user.pk).exists():
                messages.error(request, "Этот Яндекс аккаунт уже привязан к другому аккаунту.")
                return redirect("/accounts/profile/")
            user.yandex_id = social_id
        user.save()
        messages.success(request, f"{'VK' if provider == 'vk' else 'Яндекс'} аккаунт успешно привязан.")
        return redirect("/accounts/profile/")

    try:
        user = WebUser.objects.get(**({f"{provider}_id": social_id} if provider != "vk" else {"vk_id": social_id}))
    except WebUser.DoesNotExist:
        user = None

    if user is None and email:
        try:
            user = WebUser.objects.get(email=email.lower())
            setattr(user, f"{'vk' if provider == 'vk' else 'yandex'}_id", social_id)
            user.save()
        except WebUser.DoesNotExist:
            pass

    if user is None:
        name = email.split("@")[0] if email else f"{provider}_user"
        fallback_email = email.lower() if email else f"{provider}_{social_id}@noemail.letopisec"
        user = WebUser.objects.create_user(email=fallback_email, password=None, display_name=name)
        setattr(user, f"{'vk' if provider == 'vk' else 'yandex'}_id", social_id)
        user.save()
        user.initialize_bot_user()
        messages.success(request, "Аккаунт создан через социальную сеть.")

    auth.login(request, user, backend="accounts.backends.EmailBackend")
    return redirect("/")


# ── Привязка MAX ──

@login_required
def link_max(request):
    user = request.user
    if request.method == "POST" and "generate" in request.POST:
        code = user.generate_max_link_code()
        messages.info(request, f"Отправьте боту /link {code} в течение 15 минут.")
    elif request.method == "POST" and "unlink" in request.POST:
        user.is_max_linked = False
        user.max_link_code = ""
        user.save(update_fields=["is_max_linked", "max_link_code"])
        messages.success(request, "MAX аккаунт отвязан.")

    code_valid = (
        bool(user.max_link_code) and
        user.max_link_code_expires and
        user.max_link_code_expires > timezone.now()
    )
    return render(request, "accounts/link_max.html", {
        "code_valid": code_valid,
        "code": user.max_link_code if code_valid else "",
        "expires": user.max_link_code_expires,
    })
