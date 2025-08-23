# webhook.py — вход для Render (free): aiohttp + aiogram webhook
import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from Postavka import bot as main_bot, dp as main_dp, setup_handlers
from db import ensure_indexes
from reminders import process_due_reminders

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")

TOKEN = os.environ["TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_BASE")
CRON_TOKEN = os.environ.get("CRON_TOKEN", "")

if not BASE_URL:
    raise RuntimeError(
        "BASE_URL не найден. На Render это RENDER_EXTERNAL_URL (проставляется автоматически).\n"
        "Локально можно задать WEBHOOK_BASE=https://<ngrok>"
    )

bot: Bot = main_bot
dp: Dispatcher = main_dp

# регистрируем все хендлеры (калькулятор/заметки/доки/напоминания)
setup_handlers()

async def on_startup(app: web.Application):
    await ensure_indexes()  # индексы в Mongo
    url = BASE_URL.rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(url, secret_token=WEBHOOK_SECRET, drop_pending_updates=False)
    log.info("Webhook set to %s", url)

async def on_shutdown(app: web.Application):
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("Webhook deleted")
    except Exception:
        pass

async def health(_request: web.Request):
    return web.Response(text="ok")

async def cron_due(request: web.Request):
    token = request.headers.get("X-Cron-Token") or request.query.get("token")
    if not CRON_TOKEN or token != CRON_TOKEN:
        return web.Response(status=401, text="unauthorized")
    processed = await process_due_reminders(bot)
    return web.json_response({"processed": processed})

def create_app() -> web.Application:
    app = web.Application()
    # обработчик апдейтов Telegram
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET
    ).register(app, path=WEBHOOK_PATH)

    app.router.add_get("/", health)          # healthcheck
    app.router.add_post("/cron/due", cron_due)  # будильник из GitHub Actions

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    setup_application(app, dp, bot=bot)
    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
