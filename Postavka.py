# Postavka.py — основной файл бота (aiogram v3, webhook/polling)
import asyncio
import logging
from typing import Iterable, Set

import aiogram
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext

# === CONFIG ===
from config import TOKEN, ADMIN_IDS, ALLOWED_USERS
try:
    from config import TIMEZONE   # например, "Europe/Moscow"
except Exception:
    TIMEZONE = "UTC"

# === Разделы ===
from notes import register_notes_handlers
from calc import register_calc_handlers
from docs import register_docs_handlers
from reminders import register_reminders_handlers

# === Логи ===
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logging.info("Aiogram version: %s", aiogram.__version__)

# === Авторизация ===
def _ints_set(items: Iterable) -> Set[int]:
    try:
        return {int(x) for x in items}
    except Exception:
        return set()

def is_admin(user_id: int) -> bool:
    return int(user_id) in _ints_set(ADMIN_IDS)

def is_authorized(user_id: int) -> bool:
    uid = int(user_id)
    return uid in _ints_set(ADMIN_IDS) or uid in _ints_set(ALLOWED_USERS)

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
    input_field_placeholder="Выберите раздел…",
)

admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Калькулятор")],
        [KeyboardButton(text="🗒 Мои заметки")],
        [KeyboardButton(text="📁 Документы")],
        [KeyboardButton(text="🔔 Напоминания")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Админ-меню…",
)

# === Бот и диспетчер ===
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Сделаем клавиатуры доступными в других модулях
setattr(bot, "main_kb", main_kb)
setattr(bot, "admin_kb", admin_kb)

# === Команды верхнего уровня ===
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    tz_note = f"{TIMEZONE}" if TIMEZONE else "server time"
    text = (
        "*Справка*\n\n"
        "• `/start` — главное меню (сброс состояния)\n"
        "• `/whoami` — показать ваш Telegram ID\n"
        "• `/users` — список админов/пользователей (только админ)\n"
        "• `/cancel` — отмена ввода и сброс состояния\n\n"
        "*Напоминания (только админ):*\n"
        "• Кнопка: «🔔 Напоминания» — мини-справка\n"
        "• `/remind_help`\n"
        "• `/remindall YYYY-MM-DD HH:MM Текст`\n"
        "• `/remindall_daily HH:MM Текст`\n"
        "• `/remindall_weekly ДНИ HH:MM Текст`\n"
        "• `/remindall_monthly DD HH:MM Текст`\n"
        "• `/reminders`, `/delreminder ID`\n\n"
        f"_Таймзона: *{tz_note}*._"
    )
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command("whoami"))
async def cmd_whoami(message: types.Message):
    await message.reply(f"Ваш Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Команда только для админов."); return
    admins = ", ".join(map(str, sorted(_ints_set(ADMIN_IDS)))) or "—"
    users  = ", ".join(map(str, sorted(_ints_set(ALLOWED_USERS)))) or "—"
    await message.reply(
        "*Админы:*\n"
        f"`{admins}`\n\n"
        "*Допущенные пользователи:*\n"
        f"`{users}`",
        parse_mode="Markdown"
    )

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    await state.clear()  # важный сброс любых зависших состояний
    kb = admin_kb if is_admin(message.from_user.id) else main_kb
    await message.answer("Главное меню:", reply_markup=kb)

@dp.message(Command("cancel"))
async def cancel_any(message: types.Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    await state.clear()
    kb = admin_kb if is_admin(message.from_user.id) else main_kb
    await message.reply("Отменено.", reply_markup=kb)

# === Fallback: только для НЕавторизованных — для своих не мешаем
@dp.message()
async def all_other(message: types.Message):
    if not is_authorized(message.from_user.id):
        await refuse(message)
    # для авторизованных — молчим

# === Регистрация модулей ===
def setup_handlers() -> None:
    register_notes_handlers(dp, is_authorized, refuse)
    register_calc_handlers(dp, is_authorized, refuse)
    register_docs_handlers(dp, is_authorized, refuse)
    register_reminders_handlers(dp, is_authorized, refuse, bot_instance=bot)

# === Точка входа для локального запуска (polling).
# На Render (free) используйте webhook.py
async def main():
    setup_handlers()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
