"""HTTP-клиент с поддержкой прокси."""

import httpx
from bot.config import PROXY_URL


def get_client(**kwargs) -> httpx.AsyncClient:
    """Создать httpx.AsyncClient с прокси из конфига."""
    if PROXY_URL:
        kwargs.setdefault("proxy", PROXY_URL)
    kwargs.setdefault("timeout", httpx.Timeout(300.0))
    return httpx.AsyncClient(**kwargs)
