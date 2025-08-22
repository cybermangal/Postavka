# webhook.py
import os
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# импортируем ваш готовый бот/диспетчер/регистрацию хендлеров
from Postavka import bot as main_bot, dp as main_dp, setup_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# === ENV ===
TOKEN = os.environ["TOKEN"]                     # задать в Render → Environment
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")  # секрет заголовка
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook")       # путь приёма апдейтов
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_BASE")

# === Проверки ===
if not BASE_URL:
    raise RuntimeError(
        "Не вижу BASE_URL. Для Render это RENDER_EXTERNAL_URL (есть у Web Service автоматически). "
        "Локально можно задать WEBHOOK_BASE=https://<ngrok>"
    )

bot: Bot = main_bot
dp: Dispatcher = main_dp

# регистрируем все ваши хендлеры
setup_handlers()

async def on_startup(app: web.Application):
    url = BASE_URL.rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(url, secret_token=WEBHOOK_SECRET, drop_pending_updates=False)
    logger.info("Webhook set to %s", url)

async def on_shutdown(app: web.Application):
    # Можно не удалять, но аккуратнее так
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("Webhook deleted")
    except Exception:
        pass

def create_app() -> web.Application:
    app = web.Application()

    # сам обработчик Telegram
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET
    ).register(app, path=WEBHOOK_PATH)

    # healthcheck (Render дергает /)
    async def health(_request):
        return web.Response(text="ok")
    app.router.add_get("/", health)

    # хуки старта/остановки
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # важный glue между aiohttp и aiogram lifecycle
    setup_application(app, dp, bot=bot)

    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
