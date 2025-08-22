# admin.py
import json
import asyncio
from pathlib import Path
from typing import Iterable

from aiogram import types, Router
from aiogram.filters import Command

from config import ADMIN_IDS, ALLOWED_USERS  # ALLOWED_USERS — список/множество из config

ALLOWED_USERS_FILE = Path("allowed_users.json")
_lock = asyncio.Lock()
router = Router()


def _ensure_ints(items: Iterable) -> list[int]:
    out = []
    for x in items:
        try:
            out.append(int(x))
        except Exception:
            pass
    return out


def load_allowed_users() -> None:
    """Подтягиваем список из файла. Если файла нет — создаём из config.ALLOWED_USERS."""
    if ALLOWED_USERS_FILE.exists():
        try:
            data = json.loads(ALLOWED_USERS_FILE.read_text(encoding="utf-8"))
            data = _ensure_ints(data)
        except Exception:
            data = []
        # важный момент: мутируем исходный объект, чтобы ссылки в других местах не потерялись
        if isinstance(ALLOWED_USERS, set):
            ALLOWED_USERS.clear()
            ALLOWED_USERS.update(data)
        else:
            ALLOWED_USERS.clear()
            ALLOWED_USERS.extend(data)
    else:
        save_allowed_users()  # засеваем файлик текущим списком из config


def save_allowed_users() -> None:
    current = sorted(_ensure_ints(ALLOWED_USERS))
    ALLOWED_USERS_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_admin(uid: int) -> bool:
    return int(uid) in _ensure_ints(ADMIN_IDS)


def _extract_target_id(msg: types.Message) -> int | None:
    """
    Берём ID:
    1) из reply (если админ ответил на сообщение пользователя),
    2) из пересланного сообщения,
    3) из аргумента команды: /allow 123456789
    """
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    if getattr(msg, "forward_from", None):
        return msg.forward_from.id
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


@router.message(Command("allow"))
async def cmd_allow(message: types.Message):
    if not _is_admin(message.from_user.id):
        return  # тихо игнорим неадминов

    uid = _extract_target_id(message)
    if uid is None:
        await message.reply("Использование: ответьте на сообщение пользователя или укажите ID: `/allow 123456789`", parse_mode="Markdown")
        return

    async with _lock:
        load_allowed_users()
        if uid in ALLOWED_USERS or uid in _ensure_ints(ADMIN_IDS):
            await message.reply(f"Пользователь `{uid}` уже имеет доступ.", parse_mode="Markdown")
            return
        # добавляем
        if isinstance(ALLOWED_USERS, set):
            ALLOWED_USERS.add(uid)
        else:
            ALLOWED_USERS.append(uid)
        save_allowed_users()

    await message.reply(f"✅ Добавлен `{uid}`. Теперь у него есть доступ.", parse_mode="Markdown")


@router.message(Command("deny"))
async def cmd_deny(message: types.Message):
    if not _is_admin(message.from_user.id):
        return

    uid = _extract_target_id(message)
    if uid is None:
        await message.reply("Использование: ответьте на сообщение пользователя или укажите ID: `/deny 123456789`", parse_mode="Markdown")
        return

    async with _lock:
        load_allowed_users()
        if uid in _ensure_ints(ADMIN_IDS):
            await message.reply("Нельзя удалить админа из доступа.")
            return
        removed = False
        if isinstance(ALLOWED_USERS, set):
            removed = uid in ALLOWED_USERS
            ALLOWED_USERS.discard(uid)
        else:
            if uid in ALLOWED_USERS:
                ALLOWED_USERS.remove(uid)
                removed = True
        save_allowed_users()

    if removed:
        await message.reply(f"🗑 Удалён `{uid}` из списка доступа.", parse_mode="Markdown")
    else:
        await message.reply(f"Пользователя `{uid}` не было в списке.", parse_mode="Markdown")


@router.message(Command("users"))
async def cmd_users(message: types.Message):
    if not _is_admin(message.from_user.id):
        return
    load_allowed_users()
    admins = ", ".join(map(str, sorted(_ensure_ints(ADMIN_IDS)))) or "—"
    users = ", ".join(map(str, sorted(_ensure_ints(ALLOWED_USERS)))) or "—"
    text = (
        "*Админы:*\n"
        f"`{admins}`\n\n"
        "*Допущенные пользователи:*\n"
        f"`{users}`"
    )
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("whoami"))
async def cmd_whoami(message: types.Message):
    await message.reply(f"Ваш Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")


def register_admin_handlers(dp):
    """
    Подключаем роутер и подгружаем список при старте.
    Вызвать один раз из main.
    """
    load_allowed_users()
    dp.include_router(router)
