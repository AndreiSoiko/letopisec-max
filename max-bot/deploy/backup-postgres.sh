#!/usr/bin/env bash
# Ежедневный бэкап локальной PostgreSQL (transcription_bot_max).
# Запускается через systemd timer letopisec-postgres-backup.timer.
set -euo pipefail

BACKUP_DIR=/opt/letopisec/backups
RETENTION_DAYS=7
ENV_FILE=/opt/letopisec/max-bot/.env
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DUMP_FILE="$BACKUP_DIR/transcription_bot_max-$TIMESTAMP.dump"

mkdir -p "$BACKUP_DIR"

# .env — не bash-safe файл (значения со пробелами без кавычек, напр. OFERTA_DATE),
# поэтому читаем только нужные переменные через grep, не делаем `source`.
_env_get() {
    grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2-
}

DATABASE_URL=$(_env_get DATABASE_URL)
YANDEX_S3_BUCKET=$(_env_get YANDEX_S3_BUCKET)
YANDEX_S3_KEY_ID=$(_env_get YANDEX_S3_KEY_ID)
YANDEX_S3_SECRET_KEY=$(_env_get YANDEX_S3_SECRET_KEY)
export YANDEX_S3_BUCKET YANDEX_S3_KEY_ID YANDEX_S3_SECRET_KEY

pg_dump --format=custom --file="$DUMP_FILE" "$DATABASE_URL"

find "$BACKUP_DIR" -name 'transcription_bot_max-*.dump' -mtime +"$RETENTION_DAYS" -delete

# Опциональная заливка в Yandex Object Storage (тот же бакет, что и для аудио)
if [ -n "${YANDEX_S3_BUCKET:-}" ] && [ -n "${YANDEX_S3_KEY_ID:-}" ]; then
    /opt/letopisec/max-bot/venv/bin/python3 - "$DUMP_FILE" <<'PYEOF'
import os
import sys
import boto3

dump_path = sys.argv[1]
key = "backups/" + os.path.basename(dump_path)

client = boto3.client(
    "s3",
    endpoint_url="https://storage.yandexcloud.net",
    aws_access_key_id=os.environ["YANDEX_S3_KEY_ID"],
    aws_secret_access_key=os.environ["YANDEX_S3_SECRET_KEY"],
)
client.upload_file(dump_path, os.environ["YANDEX_S3_BUCKET"], key)
print(f"Uploaded {dump_path} -> s3://{os.environ['YANDEX_S3_BUCKET']}/{key}")
PYEOF
fi

echo "Backup complete: $DUMP_FILE"
