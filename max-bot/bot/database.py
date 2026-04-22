"""PostgreSQL — пользователи, балансы, подписки, платежи, транскрибации."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

from bot.config import (
    DATABASE_URL, FREE_TRIAL_MAX_MINUTES, SUBSCRIPTION_MINUTES,
    PRICE_PER_MINUTE_RUB,
)

logger = logging.getLogger(__name__)

pool: Optional[asyncpg.Pool] = None


async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    logger.info("PostgreSQL пул соединений создан")

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                trial_used BOOLEAN DEFAULT FALSE,
                star_balance INTEGER DEFAULT 0,
                free_minutes REAL DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                starts_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                minutes_total INTEGER NOT NULL DEFAULT 600,
                minutes_used REAL NOT NULL DEFAULT 0,
                stars_paid INTEGER NOT NULL,
                telegram_charge_id TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                amount_stars INTEGER NOT NULL,
                telegram_charge_id TEXT NOT NULL,
                provider_charge_id TEXT,
                payload TEXT,
                is_recurring BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS transcriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                file_name TEXT,
                duration_sec REAL NOT NULL DEFAULT 0,
                stars_spent INTEGER DEFAULT 0,
                is_trial BOOLEAN DEFAULT FALSE,
                with_theses BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'completed',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id, is_active);
            CREATE INDEX IF NOT EXISTS idx_trans_user ON transcriptions(user_id);

            CREATE TABLE IF NOT EXISTS tinkoff_orders (
                order_id TEXT PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                chat_id BIGINT,
                payment_type TEXT NOT NULL,
                amount_rub INTEGER NOT NULL,
                tinkoff_payment_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_tinkoff_user ON tinkoff_orders(user_id);
        """)

        # Миграция: добавить колонки если их нет (для обновления с v2.0)
        for col, tbl, default in [
            ("star_balance", "users", "0"),
            ("free_minutes", "users", "0"),
            ("stars_spent", "transcriptions", "0"),
            ("with_theses", "transcriptions", "FALSE"),
        ]:
            try:
                await conn.execute(f"""
                    ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col}
                    {'INTEGER' if 'int' in default or default.isdigit() else 'BOOLEAN'}
                    DEFAULT {default}
                """)
            except Exception:
                pass

        # Миграция: колонка mode для аналитики режимов работы
        try:
            await conn.execute("""
                ALTER TABLE transcriptions ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'transcribe'
            """)
        except Exception:
            pass

        # Миграция: email пользователя для фискальных чеков T-Bank
        try:
            await conn.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT
            """)
        except Exception:
            pass

        # Миграция: chat_id в tinkoff_orders для отправки сообщений после оплаты
        try:
            await conn.execute("""
                ALTER TABLE tinkoff_orders ADD COLUMN IF NOT EXISTS chat_id BIGINT
            """)
        except Exception:
            pass

    logger.info("Таблицы БД готовы")


async def close_db():
    global pool
    if pool:
        await pool.close()


# ── Пользователи ──

async def ensure_user(user_id: int, username: str = None, first_name: str = None):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
            SET username = COALESCE($2, users.username),
                first_name = COALESCE($3, users.first_name)
        """, user_id, username, first_name)


async def get_user(user_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return dict(row) if row else None


async def save_user_email(user_id: int, email: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET email = $1 WHERE user_id = $2",
            email, user_id,
        )


async def set_trial_used(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET trial_used = TRUE WHERE user_id = $1", user_id)


async def add_free_minutes(user_id: int, minutes: float):
    """Добавить бесплатные минуты (промо)."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET free_minutes = free_minutes + $1 WHERE user_id = $2",
            minutes, user_id,
        )


async def deduct_free_minutes(user_id: int, minutes: float):
    """Списать использованные бесплатные минуты."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET free_minutes = GREATEST(0, free_minutes - $1) WHERE user_id = $2",
            minutes, user_id,
        )


# ── Баланс Stars ──

async def get_star_balance(user_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT star_balance FROM users WHERE user_id = $1", user_id
        ) or 0


async def add_stars(user_id: int, amount: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET star_balance = star_balance + $1 WHERE user_id = $2",
            amount, user_id,
        )


async def deduct_stars(user_id: int, amount: int) -> bool:
    """Списать Stars. Возвращает True если хватило."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET star_balance = star_balance - $1 WHERE user_id = $2 AND star_balance >= $1",
            amount, user_id,
        )
        return "UPDATE 1" in result


# ── Подписки ──

async def get_active_subscription(user_id: int) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM subscriptions
            WHERE user_id = $1 AND is_active = TRUE AND expires_at > $2
            ORDER BY expires_at DESC LIMIT 1
        """, user_id, now)
        return dict(row) if row else None


async def create_subscription(
    user_id: int, stars_paid: int, telegram_charge_id: str,
    minutes_total: int = SUBSCRIPTION_MINUTES,
) -> dict:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO subscriptions
                (user_id, starts_at, expires_at, minutes_total, stars_paid, telegram_charge_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """, user_id, now, expires, minutes_total, stars_paid, telegram_charge_id)
        return dict(row)


async def add_minutes_used(user_id: int, minutes: float):
    sub = await get_active_subscription(user_id)
    if sub:
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE subscriptions SET minutes_used = minutes_used + $1
                WHERE id = $2
            """, minutes, sub["id"])


# ── Платежи ──

async def save_payment(
    user_id: int, amount_stars: int, telegram_charge_id: str,
    provider_charge_id: str = "", payload: str = "",
    is_recurring: bool = False,
):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO payments
                (user_id, amount_stars, telegram_charge_id, provider_charge_id, payload, is_recurring)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, user_id, amount_stars, telegram_charge_id, provider_charge_id, payload, is_recurring)


# ── Транскрибации ──

async def save_transcription(
    user_id: int, file_name: str, duration_sec: float,
    stars_spent: int = 0, is_trial: bool = False, with_theses: bool = False,
    mode: str = "transcribe",
):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO transcriptions
                (user_id, file_name, duration_sec, stars_spent, is_trial, with_theses, mode)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, user_id, file_name, duration_sec, stars_spent, is_trial, with_theses, mode)


async def get_user_stats(user_id: int) -> dict:
    async with pool.acquire() as conn:
        total = await conn.fetchrow("""
            SELECT COUNT(*) as cnt, COALESCE(SUM(duration_sec), 0) as total_sec,
                   COALESCE(SUM(stars_spent), 0) as total_stars_spent
            FROM transcriptions WHERE user_id = $1
        """, user_id)
        payments_total = await conn.fetchval("""
            SELECT COALESCE(SUM(amount_stars), 0) FROM payments WHERE user_id = $1
        """, user_id)
        return {
            "transcriptions": total["cnt"],
            "total_seconds": float(total["total_sec"]),
            "total_stars_spent": int(total["total_stars_spent"]),
            "total_stars_paid": payments_total,
        }


# ── T-Bank заказы ──

async def create_tinkoff_order(
    order_id: str, user_id: int, payment_type: str,
    amount_rub: int, tinkoff_payment_id: str, chat_id: int = None,
):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO tinkoff_orders (order_id, user_id, chat_id, payment_type, amount_rub, tinkoff_payment_id)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, order_id, user_id, chat_id, payment_type, amount_rub, tinkoff_payment_id)


async def get_tinkoff_order(order_id: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tinkoff_orders WHERE order_id = $1", order_id
        )
        return dict(row) if row else None


async def complete_tinkoff_order(order_id: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tinkoff_orders SET status = 'paid' WHERE order_id = $1", order_id
        )


# ── Проверка доступа ──

async def check_access(user_id: int, duration_sec: float) -> dict:
    """
    Проверить доступ. Варианты:
    - trial: бесплатный первый файл
    - subscription: подписка с лимитом минут
    - pay_per_minute: поминутная оплата с баланса
    - no_access: нет доступа
    """
    user = await get_user(user_id)
    if not user:
        return {"allowed": False, "reason": "user_not_found"}

    duration_min = duration_sec / 60

    # 1. Пробный
    if not user["trial_used"]:
        if duration_min <= FREE_TRIAL_MAX_MINUTES:
            return {"allowed": True, "reason": "trial", "is_trial": True, "cost_stars": 0}
        else:
            return {
                "allowed": False, "reason": "trial_too_long",
                "max_minutes": FREE_TRIAL_MAX_MINUTES,
            }

    # 1.5. Бесплатные минуты (промо)
    free_min = float(user.get("free_minutes", 0) or 0)
    if free_min >= duration_min:
        return {"allowed": True, "reason": "free_minutes", "is_trial": False, "cost_stars": 0}

    # 2. Подписка
    sub = await get_active_subscription(user_id)
    if sub:
        remaining = sub["minutes_total"] - sub["minutes_used"]
        if duration_min <= remaining:
            return {"allowed": True, "reason": "subscription", "is_trial": False, "cost_stars": 0}

    # 3. Поминутная оплата
    import math
    cost = math.ceil(duration_min) * PRICE_PER_MINUTE_RUB
    balance = user.get("star_balance", 0)
    if balance >= cost:
        return {
            "allowed": True, "reason": "pay_per_minute",
            "is_trial": False, "cost_stars": cost,
            "cost_minutes": math.ceil(duration_min),
        }

    # Нет доступа
    return {
        "allowed": False, "reason": "no_access",
        "balance": balance, "cost": cost,
        "has_subscription": sub is not None,
    }


# ── Аналитика (admin) ──

async def get_overview_stats() -> dict:
    """Общая статистика по боту для административного отчёта."""
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_subs = await conn.fetchval(
            "SELECT COUNT(*) FROM subscriptions WHERE is_active = TRUE AND expires_at > NOW()"
        )
        total_revenue = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0) FROM tinkoff_orders WHERE status = 'paid'"
        )
        trans_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(duration_sec), 0) as total_sec FROM transcriptions"
        )
        modes = await conn.fetch(
            "SELECT mode, COUNT(*) as count FROM transcriptions GROUP BY mode ORDER BY count DESC"
        )
        # Новые пользователи по дням за последние 30 дней
        daily_users = await conn.fetch("""
            SELECT DATE(created_at) as date, COUNT(*) as new_users
            FROM users
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        # Транскрибации по дням за последние 30 дней
        daily_trans = await conn.fetch("""
            SELECT DATE(created_at) as date, COUNT(*) as transcriptions,
                   COALESCE(SUM(stars_spent), 0) as revenue
            FROM transcriptions
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """)

    # Объединяем по дням
    daily_map: dict = {}
    for row in daily_users:
        d = str(row["date"])
        daily_map.setdefault(d, {"date": d, "new_users": 0, "transcriptions": 0, "revenue": 0})
        daily_map[d]["new_users"] = row["new_users"]
    for row in daily_trans:
        d = str(row["date"])
        daily_map.setdefault(d, {"date": d, "new_users": 0, "transcriptions": 0, "revenue": 0})
        daily_map[d]["transcriptions"] = row["transcriptions"]
        daily_map[d]["revenue"] = int(row["revenue"])

    return {
        "total_users": total_users,
        "active_subscriptions": active_subs,
        "total_revenue_rub": int(total_revenue),
        "total_transcriptions": trans_row["cnt"],
        "total_minutes": float(trans_row["total_sec"]) / 60,
        "modes": [{"mode": r["mode"], "count": r["count"]} for r in modes],
        "daily": sorted(daily_map.values(), key=lambda x: x["date"]),
    }


async def get_user_billing(user_id: int) -> dict:
    """Полные биллинговые данные конкретного пользователя."""
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            return {}
        sub = await conn.fetchrow("""
            SELECT * FROM subscriptions
            WHERE user_id = $1 AND is_active = TRUE AND expires_at > NOW()
            ORDER BY expires_at DESC LIMIT 1
        """, user_id)
        orders = await conn.fetch(
            "SELECT * FROM tinkoff_orders WHERE user_id = $1 ORDER BY created_at DESC", user_id
        )
        transcriptions = await conn.fetch(
            "SELECT * FROM transcriptions WHERE user_id = $1 ORDER BY created_at DESC", user_id
        )

    stats = await get_user_stats(user_id)
    return {
        "user": dict(user),
        "subscription": dict(sub) if sub else None,
        "orders": [dict(r) for r in orders],
        "transcriptions": [dict(r) for r in transcriptions],
        "stats": stats,
    }


async def get_all_users_report() -> list[dict]:
    """Список всех пользователей с агрегированной статистикой."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, u.username, u.first_name, u.created_at,
                   u.star_balance, u.trial_used,
                   COUNT(t.id) AS transcriptions_count,
                   COALESCE(SUM(t.duration_sec), 0) / 60 AS total_minutes,
                   COALESCE(SUM(t.stars_spent), 0) AS total_spent,
                   MAX(t.created_at) AS last_activity
            FROM users u
            LEFT JOIN transcriptions t ON t.user_id = u.user_id
            GROUP BY u.user_id
            ORDER BY last_activity DESC NULLS LAST
        """)
    return [dict(r) for r in rows]


async def get_payments_report() -> list[dict]:
    """Все заказы Tinkoff с данными пользователей."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT o.order_id, o.user_id, u.username, u.first_name,
                   o.payment_type, o.amount_rub, o.status,
                   o.tinkoff_payment_id, o.created_at
            FROM tinkoff_orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            ORDER BY o.created_at DESC
        """)
    return [dict(r) for r in rows]


async def get_usage_report() -> list[dict]:
    """Все транскрибации с данными пользователей и режимами."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.id, t.user_id, u.username, t.file_name, t.mode,
                   t.duration_sec / 60 AS duration_min, t.stars_spent,
                   t.is_trial, t.created_at
            FROM transcriptions t
            LEFT JOIN users u ON u.user_id = t.user_id
            ORDER BY t.created_at DESC
        """)
    return [dict(r) for r in rows]
