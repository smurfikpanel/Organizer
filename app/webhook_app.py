"""Точка входу для деплою (Render). Замість постійного опитування Telegram
(polling, як у app/bot.py для локального запуску) тут бот працює через webhook:
Telegram сам надсилає POST-запит на наш сервер щойно приходить повідомлення.
Це дозволяє безкоштовному Render web-сервісу "спати", коли бот не використовується,
і прокидатись від вхідного повідомлення."""

import logging
import os

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app.bot import bot, dp
from app.reminder_loop import reminder_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Render автоматично надає RENDER_EXTERNAL_URL з адресою сервісу — нічого вручну
# вказувати не треба. Для локального тестування вебхуку можна задати WEBHOOK_BASE_URL.
BASE_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL")


async def on_startup(app: web.Application):
    if not BASE_URL:
        logger.warning(
            "RENDER_EXTERNAL_URL/WEBHOOK_BASE_URL не задано — webhook не встановлено автоматично."
        )
        return
    webhook_url = f"{BASE_URL.rstrip('/')}{WEBHOOK_PATH}"
    await bot.set_webhook(
        webhook_url,
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )
    logger.info("Webhook встановлено: %s", webhook_url)
    import asyncio

    asyncio.create_task(reminder_loop(bot))


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()


async def health(request: web.Request) -> web.Response:
    return web.Response(text="Bot is running")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET or None,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
