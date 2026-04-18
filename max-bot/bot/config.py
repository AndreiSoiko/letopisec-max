"""Конфигурация бота MAX."""

import os
from dotenv import load_dotenv

load_dotenv()

# MAX Bot
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")

# Администраторы (user_id через запятую)
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

# PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bot:bot@localhost:5432/transcription_bot_max")

# Yandex SpeechKit
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")

# Yandex Object Storage (для async STT)
YANDEX_S3_BUCKET = os.getenv("YANDEX_S3_BUCKET", "")
YANDEX_S3_KEY_ID = os.getenv("YANDEX_S3_KEY_ID", "")
YANDEX_S3_SECRET_KEY = os.getenv("YANDEX_S3_SECRET_KEY", "")

# OpenRouter LLM
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

# Прокси
PROXY_URL = os.getenv("PROXY_URL", "")

# Пути
TEMP_DIR = os.getenv("TEMP_DIR", "data/temp")

# Лимиты файлов
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# ── Тарификация (в рублях, не Stars) ──
FREE_TRIAL_MAX_MINUTES = int(os.getenv("FREE_TRIAL_MAX_MINUTES", "41"))
SUBSCRIPTION_PRICE_RUB = int(os.getenv("SUBSCRIPTION_PRICE_RUB", "300"))
SUBSCRIPTION_MINUTES = int(os.getenv("SUBSCRIPTION_MINUTES", "600"))  # 10 часов
PRICE_PER_MINUTE_RUB = int(os.getenv("PRICE_PER_MINUTE_RUB", "4"))
THESES_PRICE_RUB = int(os.getenv("THESES_PRICE_RUB", "15"))
PROTOCOL_PRICE_RUB = int(os.getenv("PROTOCOL_PRICE_RUB", "15"))
TOPUP_AMOUNTS_RUB = [50, 100, 200]

# ── T-Bank Интернет-эквайринг ──
TINKOFF_TERMINAL_KEY = os.getenv("TINKOFF_TERMINAL_KEY", "")
TINKOFF_PASSWORD = os.getenv("TINKOFF_PASSWORD", "")
TINKOFF_TAXATION = os.getenv("TINKOFF_TAXATION", "usn_income")  # Система налогообложения
TINKOFF_NOTIFICATION_URL = os.getenv("TINKOFF_NOTIFICATION_URL", "")
TINKOFF_SUCCESS_URL = os.getenv("TINKOFF_SUCCESS_URL", "")
TINKOFF_FAIL_URL = os.getenv("TINKOFF_FAIL_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))

# Аудиоформаты
SUPPORTED_AUDIO_FORMATS = {
    "mp3", "wav", "ogg", "oga", "flac", "m4a", "aac", "wma", "webm", "opus",
}
SUPPORTED_VIDEO_FORMATS = {
    "mp4", "mkv", "avi", "mov", "wmv", "webm", "3gp", "m4v",
}
SUPPORTED_MIME_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/ogg", "audio/flac", "audio/x-flac",
    "audio/mp4", "audio/m4a", "audio/aac",
    "audio/x-ms-wma", "audio/webm", "audio/opus",
    "video/mp4", "video/x-matroska", "video/avi", "video/x-msvideo",
    "video/quicktime", "video/x-ms-wmv", "video/webm",
    "video/3gpp", "video/x-m4v",
}
ALL_SUPPORTED_FORMATS = SUPPORTED_AUDIO_FORMATS | SUPPORTED_VIDEO_FORMATS

# Чанки для Yandex SpeechKit
CHUNK_DURATION_SEC = 15
CHUNK_OVERLAP_SEC = 0

# Rate limiting
MAX_REQUESTS_PER_MINUTE = 5

# Логирование
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Промты LLM (такие же как в Telegram-версии)
CORRECTION_SYSTEM_PROMPT = """Ты — профессиональный редактор-корректор транскрибаций интервью.
Твоя задача — исправить ошибки распознавания речи, НЕ меняя смысл и стиль речи говорящего.

Правила:
1. УДАЛЯЙ дубликаты на стыках фрагментов.
2. СОХРАНЯЙ оригинальную речь максимально точно.
3. ИСПРАВЛЯЙ только очевидные ошибки распознавания.
4. ОПРЕДЕЛЯЙ тематику и используй для уточнения терминов.
5. НЕ ДОБАВЛЯЙ слова, которых не было.
6. НЕ УДАЛЯЙ слова-паразиты, оговорки — это живая речь.
7. РАССТАВЛЯЙ знаки препинания для читаемости.

Верни ТОЛЬКО исправленный текст без комментариев."""

THESES_SYSTEM_PROMPT = """Ты — аналитик, который выделяет ключевые тезисы из транскрибаций.
Выдели 5-15 основных тезисов. Нумеруй. Упоминай цифры, даты, имена.
Верни ТОЛЬКО список тезисов без пояснений."""

PROTOCOL_SYSTEM_PROMPT = """Ты — секретарь совещания. Составь протокол:
УЧАСТНИКИ, ПОВЕСТКА, ХОД ОБСУЖДЕНИЯ, ПРИНЯТЫЕ РЕШЕНИЯ,
ЗАДАЧИ И ПОРУЧЕНИЯ (ответственный, срок), ОТКРЫТЫЕ ВОПРОСЫ.
Используй ТОЛЬКО информацию из текста.
Если в тексте есть метки говорящих (Участник 1:, Участник 2: и т.д.) — используй их для идентификации участников в протоколе.
Верни ТОЛЬКО протокол."""

SPEAKER_IDENTIFICATION_PROMPT = """Ты — аналитик транскрибаций. Твоя задача: найти моменты, где участники представились по имени.

Признаки самопредставления (любое из):
- «меня зовут [Имя]», «я [Имя]», «это [Имя]»
- «моё имя [Имя]»
- участник называет своё имя в начале реплики

Верни ТОЛЬКО валидный JSON-объект вида:
{"0": "Полное Имя", "1": "Имя"}

Правила:
- Ключи — номера участников из меток «Участник N:»
- Значения — имена так, как они прозвучали (можно с фамилией)
- Включай ТОЛЬКО тех участников, чьё имя точно прозвучало
- Если никто не представился — верни пустой объект {}
- НЕ добавляй пояснений, только JSON"""
