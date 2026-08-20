"""Watchdog: проверяет сервисы/ресурсы ВМ, шлёт алерт админу через бота.

Запускается отдельно от bot.main (systemd timer), поэтому работает даже
если сам процесс бота упал — использует тот же токен, чтобы уведомление
пришло от имени бота.
"""

import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path

from maxapi import Bot
from maxapi.client.default import DefaultConnectionProperties

from bot.config import MAX_BOT_TOKEN, ADMIN_IDS
from bot.main import MAX_API_URL, _build_connector

logger = logging.getLogger(__name__)

STATE_FILE = Path("/opt/letopisec/backups/healthcheck-state.json")

SERVICES = ["letopisec", "letopisec-web", "postgresql@18-main", "nginx"]
DISK_PATH = "/"
DISK_WARN_PERCENT = 90
MEM_AVAILABLE_WARN_MB = 150


def _service_active(name: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True, text=True,
    )
    return result.stdout.strip() == "active"


def _disk_usage_percent(path: str) -> float:
    total, used, _free = shutil.disk_usage(path)
    return used / total * 100


def _mem_available_mb() -> float:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    return -1


def _collect_checks() -> dict[str, tuple[bool, str]]:
    checks: dict[str, tuple[bool, str]] = {}

    for service in SERVICES:
        ok = _service_active(service)
        checks[f"service:{service}"] = (ok, f"сервис {service} {'работает' if ok else 'НЕ активен'}")

    disk_pct = _disk_usage_percent(DISK_PATH)
    disk_ok = disk_pct < DISK_WARN_PERCENT
    checks["disk"] = (disk_ok, f"диск {DISK_PATH}: {disk_pct:.0f}% занято")

    mem_available = _mem_available_mb()
    mem_ok = mem_available < 0 or mem_available >= MEM_AVAILABLE_WARN_MB
    checks["memory"] = (mem_ok, f"доступно памяти: {mem_available:.0f} МБ")

    return checks


def _load_prev_state() -> dict[str, bool]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, bool]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def _notify(text: str) -> None:
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS не задан — уведомление не отправлено")
        return
    connector = _build_connector()
    default_conn = DefaultConnectionProperties(connector=connector) if connector else DefaultConnectionProperties()
    bot = Bot(token=MAX_BOT_TOKEN, default_connection=default_conn)
    bot.set_api_url(MAX_API_URL)
    try:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(user_id=admin_id, text=text)
            except Exception:
                logger.exception(f"Не удалось отправить уведомление админу {admin_id}")
    finally:
        await bot.close_session()


async def main() -> None:
    checks = _collect_checks()
    prev_state = _load_prev_state()

    changed_bad = []
    changed_ok = []
    for key, (ok, description) in checks.items():
        was_ok = prev_state.get(key, True)
        if ok != was_ok:
            (changed_ok if ok else changed_bad).append(description)

    if changed_bad:
        text = "🔴 Проблема на сервере letopisecmax.ru:\n" + "\n".join(f"• {d}" for d in changed_bad)
        await _notify(text)
    if changed_ok:
        text = "✅ Восстановлено:\n" + "\n".join(f"• {d}" for d in changed_ok)
        await _notify(text)

    _save_state({key: ok for key, (ok, _desc) in checks.items()})


if __name__ == "__main__":
    main_logger = logging.getLogger()
    main_logger.setLevel(logging.INFO)
    asyncio.run(main())
