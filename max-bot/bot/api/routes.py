"""Маршруты REST API."""

import asyncio
import io
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from bot.api.auth import get_current_user
from bot.api.models import (
    ApiKeyInfo, BalanceResponse, CreateApiKeyRequest, CreateApiKeyResponse,
    JobRequest, JobResponse, JobResult,
)
from bot.api.worker import process_job
from bot.database import (
    create_api_job, create_api_key, get_active_subscription, get_api_job,
    get_star_balance, get_user, list_api_jobs, list_api_keys, revoke_api_key,
)
from bot.services.docx_builder import build_docx
from bot.utils.helpers import get_temp_path

router = APIRouter(prefix="/api/v1")


# ── Баланс ──

@router.get("/balance", response_model=BalanceResponse, summary="Баланс и подписка")
async def get_balance(user_id: int = Depends(get_current_user)):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    sub = await get_active_subscription(user_id)
    remaining = None
    if sub:
        remaining = float(sub["minutes_total"]) - float(sub["minutes_used"])
    return BalanceResponse(
        star_balance=user["star_balance"] or 0,
        free_minutes=float(user.get("free_minutes") or 0),
        has_subscription=sub is not None,
        subscription_expires_at=sub["expires_at"] if sub else None,
        subscription_minutes_total=sub["minutes_total"] if sub else None,
        subscription_minutes_used=float(sub["minutes_used"]) if sub else None,
        subscription_minutes_remaining=remaining,
    )


# ── Задания ──

@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED, summary="Создать задание")
async def submit_job(req: JobRequest, user_id: int = Depends(get_current_user)):
    if req.mode == "translate" and not req.translate_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "translate_to обязателен для mode=translate")
    if req.mode == "custom" and not req.custom_prompt:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "custom_prompt обязателен для mode=custom")

    job_id = await create_api_job(
        user_id=user_id,
        mode=req.mode,
        file_url=req.url,
        language=req.language,
        translate_to=req.translate_to or "",
        custom_prompt=req.custom_prompt or "",
    )

    asyncio.create_task(process_job(job_id, user_id, {
        "mode": req.mode,
        "file_url": req.url,
        "language": req.language,
        "translate_to": req.translate_to or "",
        "custom_prompt": req.custom_prompt or "",
    }))

    job = await get_api_job(job_id, user_id)
    return _job_to_response(job)


@router.get("/jobs", response_model=List[JobResponse], summary="Список заданий")
async def list_jobs(limit: int = 20, user_id: int = Depends(get_current_user)):
    jobs = await list_api_jobs(user_id, limit=min(limit, 100))
    return [_job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse, summary="Статус задания")
async def get_job(job_id: str, user_id: int = Depends(get_current_user)):
    job = await get_api_job(job_id, user_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание не найдено")
    return _job_to_response(job)


@router.get("/jobs/{job_id}/docx", summary="Скачать результат в формате Word (.docx)")
async def download_docx(job_id: str, user_id: int = Depends(get_current_user)):
    job = await get_api_job(job_id, user_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание не найдено")
    if job["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Задание ещё не завершено (статус: {job['status']})")
    if not job.get("result_text"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Результат не найден")

    full_text = job["result_text"]
    analysis = job.get("result_analysis") or ""
    if analysis:
        final_text = f"{analysis}\n\n{'─' * 50}\n\nТРАНСКРИБАЦИЯ\n\n{full_text}"
    else:
        final_text = full_text

    duration_str = f"{int((job['duration_sec'] or 0) // 60)} мин {int((job['duration_sec'] or 0) % 60)} сек"
    docx_path = get_temp_path(user_id, f"api_{job_id[:8]}.docx")
    try:
        build_docx(
            text=final_text, output_path=docx_path,
            duration=duration_str, original_filename=job["file_url"].split("/")[-1][:100],
        )
        content = docx_path.read_bytes()
    finally:
        docx_path.unlink(missing_ok=True)

    filename = f"transcription_{job_id[:8]}.docx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── API-ключи ──

@router.get("/keys", response_model=List[ApiKeyInfo], summary="Список API-ключей")
async def list_keys(user_id: int = Depends(get_current_user)):
    return await list_api_keys(user_id)


@router.post("/keys", response_model=CreateApiKeyResponse, status_code=status.HTTP_201_CREATED, summary="Создать API-ключ")
async def create_key(req: CreateApiKeyRequest, user_id: int = Depends(get_current_user)):
    key_id, raw_key = await create_api_key(user_id, req.name)
    keys = await list_api_keys(user_id)
    key_info = next(k for k in keys if k["id"] == key_id)
    return CreateApiKeyResponse(
        id=key_id,
        name=req.name,
        key=raw_key,
        created_at=key_info["created_at"],
    )


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Отозвать API-ключ")
async def revoke_key(key_id: int, user_id: int = Depends(get_current_user)):
    ok = await revoke_api_key(key_id, user_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ключ не найден")


# ── Вспомогательные ──

def _job_to_response(job: dict) -> JobResponse:
    result = None
    if job["status"] == "done" and job.get("result_text"):
        analysis_label = None
        analysis_body = None
        raw = job.get("result_analysis") or ""
        if raw:
            parts = raw.split("\n\n", 1)
            analysis_label = parts[0]
            analysis_body = parts[1] if len(parts) > 1 else raw
        result = JobResult(
            text=job["result_text"],
            analysis=analysis_body,
            analysis_label=analysis_label,
        )
    return JobResponse(
        job_id=job["id"],
        status=job["status"],
        mode=job["mode"],
        language=job["language"],
        file_url=job["file_url"],
        duration_sec=job.get("duration_sec"),
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        result=result,
        error=job.get("error"),
    )
