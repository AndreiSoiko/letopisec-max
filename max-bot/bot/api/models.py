"""Pydantic-модели для REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class JobRequest(BaseModel):
    url: str = Field(..., description="Прямая ссылка на аудио/видео файл или Яндекс.Диск")
    mode: Literal["transcribe", "theses", "protocol", "translate", "custom"] = "transcribe"
    language: str = Field("ru-RU", description="Язык аудио (ru-RU, en-US, de-DE, fr-FR, es-ES, tr-TR)")
    translate_to: Optional[str] = Field(None, description="Язык перевода (ru, en, de, fr, es) — только для mode=translate")
    custom_prompt: Optional[str] = Field(None, description="Произвольный промт — только для mode=custom")


class JobResult(BaseModel):
    text: Optional[str] = None
    analysis: Optional[str] = None
    analysis_label: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str
    status: str
    mode: str
    language: str
    file_url: str
    duration_sec: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    result: Optional[JobResult] = None
    error: Optional[str] = None


class ApiKeyInfo(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None


class CreateApiKeyRequest(BaseModel):
    name: str = Field("", description="Название ключа для удобства")


class CreateApiKeyResponse(BaseModel):
    id: int
    name: str
    key: str = Field(..., description="Ключ — показывается только один раз!")
    created_at: datetime


class BalanceResponse(BaseModel):
    star_balance: int
    free_minutes: float
    has_subscription: bool
    subscription_expires_at: Optional[datetime] = None
    subscription_minutes_total: Optional[int] = None
    subscription_minutes_used: Optional[float] = None
    subscription_minutes_remaining: Optional[float] = None
