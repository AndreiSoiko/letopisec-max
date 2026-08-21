"""Захват метки источника перехода (?src=vk_hr_chat) для аналитики привлечения."""

import re

_SRC_RE = re.compile(r"[^A-Za-z0-9_-]")


class CaptureSourceMiddleware:
    """Сохраняет первую увиденную метку ?src= в сессию — используется при регистрации."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        src = request.GET.get("src")
        if src and not request.session.get("signup_source"):
            request.session["signup_source"] = _SRC_RE.sub("", src)[:40]
        return self.get_response(request)
