"""Аутентификация API-ключей."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bot.database import get_user_by_api_key

_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> int:
    """Зависимость FastAPI: проверяет Bearer-токен, возвращает user_id."""
    user_id = await get_user_by_api_key(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или отозванный API-ключ",
        )
    return user_id
