"""Общие фикстуры и настройки для тестов."""

import os

# Заглушки переменных окружения — должны быть установлены ДО импорта bot.*
os.environ.setdefault("MAX_BOT_TOKEN", "test_token")
os.environ.setdefault("YANDEX_API_KEY", "test_yandex_key")
os.environ.setdefault("YANDEX_FOLDER_ID", "test_folder_id")
os.environ.setdefault("YANDEX_S3_BUCKET", "test-bucket")
os.environ.setdefault("YANDEX_S3_KEY_ID", "test-key-id")
os.environ.setdefault("YANDEX_S3_SECRET_KEY", "test-secret-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test_openrouter_key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test_db")
os.environ.setdefault("TINKOFF_TERMINAL_KEY", "TinkoffBankTest")
os.environ.setdefault("TINKOFF_PASSWORD", "TestPassword")
os.environ.setdefault("ADMIN_IDS", "123456789")
