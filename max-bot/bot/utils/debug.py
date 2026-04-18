"""Система отладки — отчёты об ошибках для админов (MAX версия)."""

import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from bot.config import TEMP_DIR

logger = logging.getLogger(__name__)

_admin_ids: list[int] = []


def set_admin_ids(ids: list[int]):
    global _admin_ids
    _admin_ids = ids
    logger.info(f"Админы: {_admin_ids}")


def is_admin(user_id: int) -> bool:
    return user_id in _admin_ids


def get_first_admin() -> Optional[int]:
    return _admin_ids[0] if _admin_ids else None


async def create_error_report(
    user_id: int, file_name: str, error: Exception, extra_info: dict = None,
) -> Path:
    """Создать файл отчёта об ошибке."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tb = traceback.format_exception(type(error), error, error.__traceback__)

    lines = [
        f"═══ ОТЧЁТ ОБ ОШИБКЕ (MAX Bot) ═══",
        f"Время: {timestamp}",
        f"Пользователь: {user_id}",
        f"Файл: {file_name}",
        f"",
        f"── Ошибка ──",
        f"Тип: {type(error).__name__}",
        f"Сообщение: {str(error)}",
        f"",
        f"── Traceback ──",
        "".join(tb),
    ]

    if extra_info:
        lines.append("")
        lines.append("── Дополнительно ──")
        for k, v in extra_info.items():
            lines.append(f"{k}: {v}")

    report_dir = Path(TEMP_DIR)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_filename = f"error_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    report_path = report_dir / report_filename

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return report_path
