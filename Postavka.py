# Postavka.py — основной файл бота (aiogram v3, webhook/polling)
import asyncio
import logging
from typing import Iterable, Set

import aiogram
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import Command
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext

from config import TOKEN, ADMIN_IDS, ALLOWED_USERS
try:
    from config import TIMEZONE
except Exception:
    TIMEZONE = "UTC"

# Разделы
from notes import register_notes_handlers
from calc import register_calc_handlers
from docs import register_docs_handlers
from reminders import register_reminders_handlers

# Доступ (Mongo)
from db import get_allowed_set, add_allowed, remove_allowed

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logging.info("Aiogram version: %s", aiogram.__version__)

# === Авторизация ===
def _ints_set(items: Iterable) -> Set[int]:
    try:
        return {int(x) for x in items}
    except Exception:
        return set()

ENV_ADMINS = _ints_set(ADMIN_IDS)
ENV_ALLOWED = _ints_set(ALLOWED_USERS)

def is_admin(user_id: int) -> bool:
    return int(user_id) in ENV_ADMINS

def is_authorized(user_id: int) -> bool:
    uid = int(user_id)
    dyn: Set[int] = getattr(bot, "allowed_dynamic", set())
    return uid in ENV_ADMINS or uid in ENV_ALLOWED or uid in dyn

async def refuse(message: types.Message):
    await message.answer(
        "⛔️ Доступ запрещён!\n\n"
        f"Ваш Telegram ID: `{message.from_user.id}`\n"
        "Сообщите этот ID администратору, чтобы получить доступ.",
        parse_mode="Markdown",
    )

# === Клавиатуры ===
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Калькулятор")],
        [KeyboardButton(text="🗒 Мои заметки")],
        [KeyboardButton(text="📁 Документы")],
    ],
    resize_keyboard=True,
)
admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Калькулятор")],
        [KeyboardButton(text="🗒 Мои заметки")],
        [KeyboardButton(text="📁 Документы")],
        [KeyboardButton(text="🔔 Напоминания")],
    ],
    resize_keyboard=True,
)

# === Бот и диспетчер ===
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# доступен в других модулях
setattr(bot, "main_kb", main_kb)
setattr(bot, "admin_kb", admin_kb)
setattr(bot, "allowed_dynamic", set())  # будет заполнено на старте

# ====== Управление доступом (команды только для админов) ======
@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Команда только для админов."); return
    dyn: Set[int] = getattr(bot, "allowed_dynamic", set())
    admins = ", ".join(map(str, sorted(ENV_ADMINS))) or "—"
    allowed_env = ", ".join(map(str, sorted(ENV_ALLOWED))) or "—"
    allowed_db = ", ".join(map(str, sorted(dyn))) or "—"
    await message.reply(
        "*Админы (ENV):*\n"
        f"`{admins}`\n\n"
        "*Допущенные (ENV):*\n"
        f"`{allowed_env}`\n\n"
        "*Допущенные (Mongo):*\n"
        f"`{allowed_db}`",
        parse_mode="Markdown"
    )

@dp.message(Command("allowlist"))
async def cmd_allowlist(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Команда только для админов."); return
    dyn: Set[int] = getattr(bot, "allowed_dynamic", set())
    txt = ", ".join(map(str, sorted(dyn))) or "—"
    await message.reply(f"*Mongo allowlist:*\n`{txt}`", parse_mode="Markdown")

@dp.message(Command("allow"))
async def cmd_allow(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Команда только для админов."); return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.reply("Использование: `/allow <telegram_id>`", parse_mode="Markdown")
        return
    uid = int(parts[1])
    await add_allowed(uid)
    # обновим кэш
    bot.allowed_dynamic = await get_allowed_set()
    await message.reply(f"✅ Пользователь `{uid}` добавлен в доступ (Mongo).", parse_mode="Markdown")

@dp.message(Command("allowme"))
async def cmd_allowme(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Команда только для админов."); return
    uid = int(message.from_user.id)
    await add_allowed(uid)
    bot.allowed_dynamic = await get_allowed_set()
    await message.reply(f"✅ Вы добавлены в доступ (Mongo): `{uid}`", parse_mode="Markdown")

@dp.message(Command("deny"))
async def cmd_deny(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Команда только для админов."); return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.reply("Использование: `/deny <telegram_id>`", parse_mode="Markdown")
        return
    uid = int(parts[1])
    await remove_allowed(uid)
    bot.allowed_dynamic = await get_allowed_set()
    await message.reply(f"🗑 Пользователь `{uid}` удалён из доступа (Mongo).", parse_mode="Markdown")

# === Базовые команды ===
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    tz_note = f"{TIMEZONE}" if TIMEZONE else "server time"
    text = (
        "*Справка*\n\n"
        "• `/start` — главное меню (сброс состояния)\n"
        "• `/whoami` — ваш Telegram ID\n"
        "• `/cancel` — отмена ввода и сброс состояния\n\n"
        "*Доступ (только админ):*\n"
        "• `/users` — показать списки (ENV + Mongo)\n"
        "• `/allow <id>` — выдать доступ\n"
        "• `/deny <id>` — отозвать доступ\n"
        "• `/allowme` — выдать доступ себе\n"
        "• `/allowlist` — показать Mongo-список\n\n"
        "*Напоминания (только админ):*\n"
        "• «🔔 Напоминания» / `/remind_help` и команды\n\n"
        f"_Таймзона: *{tz_note}*._"
    )
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command("whoami"))
async def cmd_whoami(message: types.Message):
    await message.reply(f"Ваш Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    await state.clear()
    kb = admin_kb if is_admin(message.from_user.id) else main_kb
    await message.answer("Главное меню:", reply_markup=kb)

@dp.message(Command("cancel"))
async def cancel_any(message: types.Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    await state.clear()
    kb = admin_kb if is_admin(message.from_user.id) else main_kb
    await message.reply("Отменено.", reply_markup=kb)

# === Fallback — только для неавторизованных, подключим последним
fallback_router = Router(name="fallback")

@fallback_router.message()
async def all_other(message: types.Message):
    if not is_authorized(message.from_user.id):
        await refuse(message)
    # для авторизованных молчим — даём отработать узким хэндлерам

# === Регистрация модулей ===
def setup_handlers() -> None:
    register_notes_handlers(dp, is_authorized, refuse)
    register_calc_handlers(dp, is_authorized, refuse)
    register_docs_handlers(dp, is_authorized, refuse)
    register_reminders_handlers(dp, is_authorized, refuse, bot_instance=bot)
    dp.include_router(fallback_router)

# Вспомогательная функция — загрузка allowlist из Mongo (вызовем при старте веб-приложения)
async def refresh_access_cache():
    bot.allowed_dynamic = await get_allowed_set()

# Локальный запуск (polling)
async def main():
    setup_handlers()
    await refresh_access_cache()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

