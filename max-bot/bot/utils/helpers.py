"""Вспомогательные функции."""

import time
from pathlib import Path
from collections import defaultdict

from bot.config import TEMP_DIR, MAX_REQUESTS_PER_MINUTE


def ensure_temp_dir() -> Path:
    path = Path(TEMP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_temp_path(user_id: int, filename: str) -> Path:
    user_dir = ensure_temp_dir() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / filename


def cleanup_user_files(user_id: int) -> None:
    user_dir = ensure_temp_dir() / str(user_id)
    if user_dir.exists():
        for f in user_dir.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        try:
            user_dir.rmdir()
        except OSError:
            pass


def format_duration(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} КБ"
    return f"{size_bytes / (1024 * 1024):.1f} МБ"


def get_file_extension(filename: str) -> str:
    return Path(filename).suffix.lstrip(".").lower()


class RateLimiter:
    def __init__(self, max_requests: int = MAX_REQUESTS_PER_MINUTE, window: int = 60):
        self.max_requests = max_requests
        self.window = window
        self._requests: dict[int, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        now = time.time()
        self._requests[user_id] = [
            t for t in self._requests[user_id] if now - t < self.window
        ]
        if len(self._requests[user_id]) >= self.max_requests:
            return False
        self._requests[user_id].append(now)
        return True


rate_limiter = RateLimiter()
