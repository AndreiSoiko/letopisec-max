"""Разовая рассылка всем пользователям бота.

Запускается вручную через SSH: python -m bot.broadcast_once [--dry-run]
Не ставится на systemd — одноразовый скрипт.
"""

import argparse
import asyncio
import logging

from maxapi import Bot
from maxapi.client.default import DefaultConnectionProperties

from bot.config import MAX_BOT_TOKEN
from bot.database import init_db, close_db, get_all_user_ids
from bot.main import MAX_API_URL, _build_connector

logger = logging.getLogger(__name__)

ANNOUNCEMENT_TEXT = (
    "🎉 Новая функция в Летописце!\n\n"
    "Теперь можно прислать не только файл, но и ссылку на видео —\n"
    "VK Video, Rutube, OK.ru, Vimeo, TikTok, Яндекс.Диск и другие —\n"
    "бот распознает аудио прямо по ссылке, без скачивания.\n\n"
    "🎁 Промокод SUPER3 — подписка на 3 месяца всего за 200 ₽\n"
    "(вместо 900 ₽ при обычной покупке)\n"
    "Активировать: отправьте боту команду /promo super3\n\n"
    "Команда /menu — все возможности бота."
)

DELAY_SECONDS = 0.4


async def main(dry_run: bool) -> None:
    await init_db()
    try:
        user_ids = await get_all_user_ids()
    finally:
        await close_db()

    print(f"Получателей: {len(user_ids)}")
    if dry_run:
        print("--dry-run: сообщения не отправлены.")
        return

    connector = _build_connector()
    default_conn = DefaultConnectionProperties(connector=connector) if connector else DefaultConnectionProperties()
    bot = Bot(token=MAX_BOT_TOKEN, default_connection=default_conn)
    bot.set_api_url(MAX_API_URL)

    sent, failed = 0, 0
    try:
        for user_id in user_ids:
            try:
                await bot.send_message(user_id=user_id, text=ANNOUNCEMENT_TEXT)
                sent += 1
            except Exception:
                failed += 1
                logger.warning("Не удалось отправить пользователю %s", user_id, exc_info=True)
            await asyncio.sleep(DELAY_SECONDS)
    finally:
        await bot.close_session()

    print(f"Отправлено: {sent}, ошибок: {failed}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Только посчитать получателей, не отправлять")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
