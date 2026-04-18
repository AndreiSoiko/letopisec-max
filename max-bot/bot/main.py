"""Точка входа — бот транскрибации для MAX."""

import asyncio
import logging
import sys

from maxapi import Bot, Dispatcher


from bot.config import (
    MAX_BOT_TOKEN, LOG_LEVEL, YANDEX_API_KEY, OPENROUTER_API_KEY, ADMIN_IDS,
    TINKOFF_TERMINAL_KEY, WEBHOOK_PORT,
)
from bot.database import init_db, close_db
from bot.utils.debug import set_admin_ids
from bot.handlers import register_start_handlers, register_payment_handlers, register_transcribe_handlers, register_admin_handlers


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    if not MAX_BOT_TOKEN:
        logger.error("❌ MAX_BOT_TOKEN не задан в .env")
        sys.exit(1)
    if not YANDEX_API_KEY:
        logger.warning("⚠️ YANDEX_API_KEY не задан")
    if not OPENROUTER_API_KEY:
        logger.warning("⚠️ OPENROUTER_API_KEY не задан")

    # PostgreSQL
    await init_db()

    # Админы
    set_admin_ids(ADMIN_IDS)

    # MAX Bot
    bot = Bot(token=MAX_BOT_TOKEN)
    dp = Dispatcher()

    # Регистрация обработчиков
    register_admin_handlers(dp, bot)
    register_start_handlers(dp, bot)
    register_payment_handlers(dp, bot)
    register_transcribe_handlers(dp, bot)

    # Webhook-сервер для уведомлений T-Bank (отдельный поток)
    if TINKOFF_TERMINAL_KEY:
        from bot.webhook import start_webhook_thread
        loop = asyncio.get_event_loop()
        start_webhook_thread(bot, loop, WEBHOOK_PORT)
    else:
        logger.warning("   💳  TINKOFF_TERMINAL_KEY не задан — оплата отключена")

    logger.info("🎙 MAX-бот транскрибации запущен!")
    logger.info(f"   STT: Yandex SpeechKit")
    logger.info(f"   LLM: OpenRouter {'✅' if OPENROUTER_API_KEY else '❌'}")
    logger.info(f"   DB:  PostgreSQL ✅")
    logger.info(f"   💳  T-Bank эквайринг {'✅' if TINKOFF_TERMINAL_KEY else '❌'}")
    logger.info(f"   🎬  Видео: MP4, MKV, AVI, MOV, WebM ✅")

    try:
        # Удаляем webhook перед polling (если был установлен)
        await bot.delete_webhook()
        await dp.start_polling(bot)
    finally:
        await close_db()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
