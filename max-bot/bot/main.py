"""Точка входа — бот транскрибации для MAX."""

import asyncio
import logging
import os
import ssl
import sys

import aiohttp
from maxapi import Bot, Dispatcher
from maxapi.client.default import DefaultConnectionProperties


from bot.config import (
    MAX_BOT_TOKEN, LOG_LEVEL, YANDEX_API_KEY, ADMIN_IDS,
    TINKOFF_TERMINAL_KEY, WEBHOOK_PORT, API_PORT,
)
from bot.database import init_db, close_db, fail_stale_jobs
from bot.utils.debug import set_admin_ids
from bot.handlers import register_start_handlers, register_payment_handlers, register_transcribe_handlers, register_admin_handlers

MAX_API_URL = "https://platform-api2.max.ru"
# Путь к сертификату Минцифры (скачать: https://www.gosuslugi.ru/crt)
MAX_SSL_CA_CERT = os.getenv("MAX_SSL_CA_CERT", "")


def _build_connector() -> aiohttp.TCPConnector | None:
    """Создаёт TCPConnector с сертификатом Минцифры, если файл задан."""
    if not MAX_SSL_CA_CERT or not os.path.exists(MAX_SSL_CA_CERT):
        return None
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.load_verify_locations(MAX_SSL_CA_CERT)
    return aiohttp.TCPConnector(ssl=ssl_ctx)


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

    # PostgreSQL
    await init_db()
    await fail_stale_jobs()

    # Админы
    set_admin_ids(ADMIN_IDS)

    # MAX Bot
    connector = _build_connector()
    default_conn = DefaultConnectionProperties(connector=connector) if connector else DefaultConnectionProperties()
    bot = Bot(token=MAX_BOT_TOKEN, default_connection=default_conn)
    bot.set_api_url(MAX_API_URL)
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
    logger.info(f"   LLM: YandexGPT-32k {'✅' if YANDEX_API_KEY else '❌'}")
    logger.info(f"   DB:  PostgreSQL ✅")
    logger.info(f"   💳  T-Bank эквайринг {'✅' if TINKOFF_TERMINAL_KEY else '❌'}")
    logger.info(f"   🎬  Видео: MP4, MKV, AVI, MOV, WebM ✅")
    logger.info(f"   🌐  REST API: http://0.0.0.0:{API_PORT}/api/docs")

    # REST API сервер (uvicorn в том же event loop)
    import uvicorn
    from bot.api.app import create_app
    api_config = uvicorn.Config(
        create_app(), host="0.0.0.0", port=API_PORT,
        log_level="warning", loop="none",
    )
    api_server = uvicorn.Server(api_config)

    try:
        await bot.delete_webhook()
        await asyncio.gather(
            dp.start_polling(bot),
            api_server.serve(),
        )
    finally:
        await close_db()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
