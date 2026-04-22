"""HTTP-сервер для уведомлений T-Bank — отдельный поток, не блокирует bot polling."""

import asyncio
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from bot.services.tinkoff import verify_notification
from bot.database import (
    get_tinkoff_order, complete_tinkoff_order,
    add_stars, create_subscription, get_star_balance, save_payment,
)
from bot.config import (
    SUBSCRIPTION_MINUTES, OFERTA_DATE,
    FREE_TRIAL_MAX_MINUTES, SUBSCRIPTION_PRICE_RUB,
    PRICE_PER_MINUTE_RUB, THESES_PRICE_RUB, PROTOCOL_PRICE_RUB,
)
from bot.handlers.payment import _menu_kb

_OFERTA_TEMPLATE_PATH = Path(__file__).parent.parent / "oferta-max-bot.md"


def _render_oferta_html() -> str:
    """Читает markdown-шаблон оферты, подставляет значения из конфига, возвращает HTML."""
    try:
        md = _OFERTA_TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<p>Файл оферты не найден.</p>"

    subscription_hours = SUBSCRIPTION_MINUTES // 60
    md = md.format(
        OFERTA_DATE=OFERTA_DATE,
        FREE_TRIAL_MAX_MINUTES=FREE_TRIAL_MAX_MINUTES,
        SUBSCRIPTION_PRICE_RUB=SUBSCRIPTION_PRICE_RUB,
        SUBSCRIPTION_HOURS=subscription_hours,
        PRICE_PER_MINUTE_RUB=PRICE_PER_MINUTE_RUB,
        THESES_PRICE_RUB=THESES_PRICE_RUB,
        PROTOCOL_PRICE_RUB=PROTOCOL_PRICE_RUB,
    )

    # Конвертация markdown → HTML
    import re
    lines = md.split("\n")
    html_lines = []
    in_list = False
    for line in lines:
        if line.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = line[2:]
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            html_lines.append(f"<li>{content}</li>")
        elif line.strip() == "---":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<hr>")
        elif line.strip() == "":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            content = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', content)
            html_lines.append(f"<p>{content}</p>")
    if in_list:
        html_lines.append("</ul>")

    body = "\n".join(html_lines)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Публичная оферта — Летописец</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.6; }}
  h1 {{ font-size: 1.6em; }} h2 {{ font-size: 1.2em; margin-top: 2em; }} h3 {{ font-size: 1em; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 1.5em 0; }}
  ul {{ padding-left: 1.5em; }} li {{ margin: 0.3em 0; }}
  a {{ color: #0066cc; }}
</style>
</head>
<body>
{body}
</body>
</html>"""

logger = logging.getLogger(__name__)

# Ссылки на главный event loop и бота — устанавливаются при старте
_loop: asyncio.AbstractEventLoop | None = None
_bot = None


def _run(coro):
    """Выполнить корутину в главном event loop из стороннего потока."""
    assert _loop is not None, "Webhook loop не инициализирован"
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=30)


async def _process_payment(data: dict) -> str:
    """Обработать подтверждённый платёж. Возвращает 'OK' или текст ошибки."""
    order_id = data.get("OrderId", "")
    order = await get_tinkoff_order(order_id)
    if not order:
        logger.warning("T-Bank notify: заказ не найден: %s", order_id)
        return "OK"

    if order["status"] == "paid":
        return "OK"

    await complete_tinkoff_order(order_id)

    user_id = order["user_id"]
    chat_id = order.get("chat_id") or user_id
    payment_type = order["payment_type"]
    amount_rub = order["amount_rub"]
    payment_id = str(order.get("tinkoff_payment_id", ""))

    try:
        await save_payment(
            user_id=user_id,
            amount_stars=amount_rub,
            telegram_charge_id=payment_id,
            payload=order_id,
        )
    except Exception as exc:
        logger.error("Ошибка сохранения payment: %s", exc)

    if payment_type == "topup":
        await add_stars(user_id, amount_rub)
        balance = await get_star_balance(user_id)
        await _bot.send_message(
            chat_id=chat_id,
            text=f"✅ Баланс пополнен на {amount_rub} ₽\n💰 Текущий баланс: {balance} ₽",
            attachments=[_menu_kb()],
        )

    elif payment_type == "subscription":
        sub = await create_subscription(
            user_id=user_id,
            stars_paid=amount_rub,
            telegram_charge_id=payment_id,
            minutes_total=SUBSCRIPTION_MINUTES,
        )
        exp = sub["expires_at"].strftime("%d.%m.%Y")
        hours = SUBSCRIPTION_MINUTES // 60
        await _bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ Подписка активирована!\n"
                f"📅 Действует до {exp}\n"
                f"⏱ {hours} часов распознавания\n"
                f"🎯 Тезисы и протокол включены"
            ),
            attachments=[_menu_kb()],
        )

    return "OK"


class _TinkoffHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/oferta":
            html = _render_oferta_html()
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._respond(404, "NOT FOUND")

    def do_POST(self):
        if self.path != "/tinkoff/notify":
            self._respond(404, "NOT FOUND")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
        except Exception:
            logger.warning("T-Bank notify: не удалось разобрать JSON")
            self._respond(400, "BAD REQUEST")
            return

        logger.info(
            "T-Bank notify: status=%s order=%s",
            data.get("Status"), data.get("OrderId"),
        )

        if not verify_notification(data):
            logger.warning("T-Bank notify: неверная подпись")
            self._respond(400, "INVALID TOKEN")
            return

        if data.get("Status") != "CONFIRMED":
            self._respond(200, "OK")
            return

        try:
            _run(_process_payment(data))
        except Exception as exc:
            logger.error("Ошибка обработки платежа: %s", exc)

        self._respond(200, "OK")

    def _respond(self, code: int, text: str):
        self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(text.encode())
        self.wfile.flush()

    def log_message(self, format, *args):
        pass  # логирование через стандартный logger выше


def start_webhook_thread(bot, loop: asyncio.AbstractEventLoop, port: int) -> threading.Thread:
    """Запустить HTTP-сервер в отдельном daemon-потоке."""
    global _loop, _bot
    _loop = loop
    _bot = bot

    server = HTTPServer(("0.0.0.0", port), _TinkoffHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("💳 T-Bank webhook запущен в отдельном потоке: http://0.0.0.0:%d/tinkoff/notify", port)
    return thread


# Для обратной совместимости (Docker / Linux — там aiohttp работало)
def build_app(bot):
    """Устаревший метод — оставлен для совместимости."""
    from aiohttp import web

    async def _handle(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.Response(text="BAD REQUEST", status=400)

        logger.info("T-Bank notify: status=%s order=%s", data.get("Status"), data.get("OrderId"))

        if not verify_notification(data):
            return web.Response(text="INVALID TOKEN", status=400)

        if data.get("Status") != "CONFIRMED":
            return web.Response(text="OK")

        try:
            await _process_payment(data)
        except Exception as exc:
            logger.error("Ошибка обработки платежа: %s", exc)

        return web.Response(text="OK")

    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/tinkoff/notify", _handle)
    return app
