# Postavka.py — основной файл бота (aiogram v3)
import asyncio
import logging
from typing import Iterable, Set

import aiogram
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.storage.memory import MemoryStorage

# === CONFIG ===
# В config.py должны быть:
# TOKEN, ADMIN_IDS (list|set), ALLOWED_USERS (list|set)
from config import TOKEN, ADMIN_IDS, ALLOWED_USERS
try:
    from config import TIMEZONE   # например, "Europe/Samara"
except Exception:
    TIMEZONE = "UTC"

# === Разделы ===
from notes import register_notes_handlers
from calc import register_calc_handlers
from docs import register_docs_handlers

# === Напоминания (отдельный модуль) ===
# Файл reminders.py должен лежать рядом
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
        [KeyboardButton(text="🔔 Напоминания")],   # кнопка для админов — обрабатывается в reminders.py
    ],
    resize_keyboard=True,
    input_field_placeholder="Админ-меню…",
)

# === Бот и диспетчер ===
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# === Команды верхнего уровня ===
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    tz_note = f"{TIMEZONE}" if TIMEZONE else "server time"
    text = (
        "*Справка*\n\n"
        "• `/start` — главное меню\n"
        "• `/whoami` — показать ваш Telegram ID\n"
        "• `/users` — список админов/пользователей (только админ)\n\n"
        "*Напоминания (только админ):*\n"
        "• Кнопка: «🔔 Напоминания» — мини-справка\n"
        "• `/remind_help` — мини-справка по напоминаниям\n"
        "• `/remindall YYYY-MM-DD HH:MM Текст` — разовая рассылка\n"
        "• `/remindall_daily HH:MM Текст` — ежедневно\n"
        "• `/remindall_weekly ДНИ HH:MM Текст` — еженедельно (например: `пн,ср,пт` или `mon,fri`)\n"
        "• `/remindall_monthly DD HH:MM Текст` — ежемесячно (день 1–31)\n"
        "• `/reminders` — список напоминаний\n"
        "• `/delreminder ID` — удалить напоминание\n\n"
        f"_Время интерпретируется в таймзоне: *{tz_note}*._"
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

# === /start ===
@dp.message(Command("start"))
async def start(message: types.Message):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    kb = admin_kb if is_admin(message.from_user.id) else main_kb
    await message.answer("Главное меню:", reply_markup=kb)

# === Страхующее меню для трёх основных кнопок ===
menu_router = Router(name="menu")

@menu_router.message(F.text.in_({"📊 Калькулятор", "🗒 Мои заметки", "📁 Документы"}))
async def menu_entry(message: types.Message):
    if not is_authorized(message.from_user.id):
        await refuse(message); return
    mapping = {
        "📊 Калькулятор": "Раздел «Калькулятор». Что считаем?",
        "🗒 Мои заметки": "Раздел «Заметки». Готов записывать.",
        "📁 Документы":   "Раздел «Документы». Что открыть?",
    }
    kb = admin_kb if is_admin(message.from_user.id) else main_kb
    await message.answer(mapping.get(message.text, "Ок"), reply_markup=kb)

# === Fallback: только если никто не сработал ===
fallback_router = Router(name="fallback")

@fallback_router.message()
async def all_other(message: types.Message):
    if not is_authorized(message.from_user.id):
        await refuse(message)
    # для своих — молчим

# === Регистрация всех модулей/роутеров ===
def setup_handlers() -> None:
    # 1) Страхующее меню
    dp.include_router(menu_router)

    # 2) Разделы
    register_notes_handlers(dp, is_authorized, refuse)
    register_calc_handlers(dp, is_authorized, refuse)
    register_docs_handlers(dp, is_authorized, refuse)

    # 3) Напоминания: кнопка «🔔 Напоминания» и все команды (важно: корректный вызов!)
    register_reminders_handlers(dp, is_authorized, refuse, bot_instance=bot)

    # 4) Общий ловец в самом конце
    dp.include_router(fallback_router)

# === Точка входа ===
async def main():
    setup_handlers()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
