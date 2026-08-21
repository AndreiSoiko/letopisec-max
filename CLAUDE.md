# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Letopisec** is a MAX Messenger bot for audio/video transcription and intelligent document processing. It transcribes meetings/recordings via Yandex SpeechKit and optionally runs AI post-processing (text correction, key theses extraction, meeting protocol generation) using OpenRouter LLMs, then outputs formatted Word (.docx) documents.

## Running the Bot

```bash
cd max-bot
pip install -r requirements.txt
# Requires ffmpeg installed system-wide
python -m bot.main
```

Or with Docker (includes PostgreSQL):
```bash
cd max-bot
docker-compose up
```

## Environment Setup

Copy `.env.example` to `.env` in `max-bot/`. Required variables:

| Variable | Purpose |
|----------|---------|
| `MAX_BOT_TOKEN` | MAX Messenger bot token |
| `YANDEX_API_KEY` | Yandex Cloud SpeechKit API key |
| `YANDEX_FOLDER_ID` | Yandex Cloud folder ID |
| `DATABASE_URL` | PostgreSQL connection string |
| `OPENROUTER_API_KEY` | LLM provider for corrections/theses/protocol |
| `TINKOFF_TERMINAL_KEY` | T-Bank payment terminal (optional) |
| `TINKOFF_PASSWORD` | T-Bank password (optional) |
| `ADMIN_IDS` | Comma-separated admin user IDs |

Pricing, LLM model selection, file size limits, and rate limiting are also configured via `.env` (see `bot/config.py` for all options).

## Architecture

### Request Flow

1. User uploads audio/video → `handlers/transcribe.py`
2. `services/audio.py` extracts audio (ffmpeg) and splits into 15s WAV chunks
3. `services/yandex_stt.py` transcribes each chunk (sync API) or whole file (async API via S3)
4. Optional post-processing selected by user:
   - `services/correction.py` — LLM fixes STT errors (10k char blocks, 500 char overlap)
   - `services/theses.py` — LLM extracts 5–15 key points
   - `services/protocol.py` — LLM generates meeting notes (participants, decisions, tasks)
5. `services/docx_builder.py` creates formatted Word document
6. `database.py` debits user account (trial / subscription / pay-per-minute)

### Payment Flow

User → `handlers/payment.py` → `services/tinkoff.py` (creates T-Bank order) → T-Bank page → webhook POST to `/tinkoff/notify` → `webhook.py` → `database.py` credits account

### Key Modules

| Module | Role |
|--------|------|
| `bot/main.py` | Entry point; initializes DB pool, bot, handlers, webhook server |
| `bot/config.py` | All env vars, pricing, LLM prompts, supported media formats |
| `bot/database.py` | All PostgreSQL operations (users, subscriptions, payments, transcriptions, T-Bank orders) |
| `bot/webhook.py` | aiohttp server for T-Bank payment notifications |
| `handlers/start.py` | `/start`, `/help`, `/menu`, promo codes |
| `handlers/transcribe.py` | File upload handling, transcription pipeline orchestration |
| `handlers/payment.py` | Balance, subscriptions, top-up flows |
| `services/audio.py` | ffmpeg wrappers: extract, convert, split, duration |
| `services/yandex_stt.py` | Yandex SpeechKit sync and async APIs |
| `utils/helpers.py` | Temp file management, duration/size formatting, per-user rate limiting (5 req/min) |
| `utils/debug.py` | Admin error reporting |

### Database Schema

- `users` — user_id, trial_used, star_balance, free_minutes
- `subscriptions` — user_id, expires_at, minutes_total, minutes_used
- `payments` — user_id, amount, charge_id
- `transcriptions` — user_id, file_name, duration_sec, flags
- `tinkoff_orders` — order_id, user_id, payment_type, amount_rub, status

## Technology Stack

- **maxapi** — MAX Messenger bot framework (async)
- **asyncpg** — PostgreSQL async driver
- **aiohttp** — Webhook server
- **httpx** — HTTP client
- **python-docx** — Word document generation
- **boto3** — Yandex S3 (async STT uploads)
- **ffmpeg** — Audio/video processing (system dependency)

## Production Deployment (VM)

The bot and web app run directly on a Yandex Cloud VM (no Docker in prod). Claude has no SSH access to this VM from the sandbox — any command here must be run by the user.

- Host: `81.26.183.201`, user `letopisec-max`, project at `/opt/letopisec` (bot in `max-bot/`, web in `web/`)
- systemd services: `letopisec` (bot), `letopisec-web` (Django/gunicorn, web/deploy/letopisec-web.service), `letopisec-healthcheck.service`, `letopisec-postgres-backup.service`
- Web app venv on the VM: `/home/letopisec-max/web-venv`
- DB: managed PostgreSQL cluster in Yandex Cloud (not a local container)

**Whenever giving the user commands to run on this VM, always format them as a single bash code block:**
- Steps numbered as shell comments (`# 1. ...`, `# 2. ...`) placed *above* the command they describe, not after it
- Each comment explains what the command does and why, in plain language — don't assume familiarity with Django/systemd internals
- No references to earlier chat context ("as discussed above", "the command from step 1") — the block must be self-contained and copy-pasteable on its own

Example:
```bash
# 1. подключение к серверу по SSH
ssh letopisec-max@81.26.183.201

# 2. переход в папку проекта и скачивание последних изменений кода
cd /opt/letopisec && git pull

# 3. перезапуск процесса сайта, чтобы подхватились изменения
sudo systemctl restart letopisec-web
```

## Notes

- All code is async (`asyncio`). The entire pipeline is async from handlers through services to DB.
- LLM prompts are in Russian and stored in `bot/config.py`.
- The transcription handler (`handlers/transcribe.py`) was under active development — attachment parsing logic may be incomplete.
- T-Bank webhook uses SHA-256 token verification; orders are processed idempotently.
- Docker PostgreSQL: host `db`, port `5432` (internal) / `5434` (external), database `transcription_bot_max`.
