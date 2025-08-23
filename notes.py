# notes.py — простые пользовательские заметки с MongoDB
from datetime import datetime, timezone
from typing import List

from aiogram import types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command

from db import notes as col

notes_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить заметку")],
        [KeyboardButton(text="📄 Список заметок")],
        [KeyboardButton(text="⬅️ В меню")],
    ],
    resize_keyboard=True,
)

async def _add_note(user_id: int, text: str) -> str:
    doc = {"user_id": int(user_id), "text": text, "created_at": datetime.now(timezone.utc)}
    res = await col.insert_one(doc)
    return str(res.inserted_id)

async def _list_notes(user_id: int, limit: int = 20) -> List[dict]:
    cur = col.find({"user_id": int(user_id)}).sort("created_at", -1).limit(limit)
    return [doc async for doc in cur]

async def _delete_note(user_id: int, idx: int) -> bool:
    # удаление по порядковому номеру в текущей выдаче
    items = await _list_notes(user_id, limit=50)
    if 1 <= idx <= len(items):
        target = items[idx - 1]
        res = await col.delete_one({"_id": target["_id"], "user_id": int(user_id)})
        return res.deleted_count == 1
    return False

def register_notes_handlers(dp, is_authorized, refuse):

    @dp.message(F.text == "🗒 Мои заметки")
    async def notes_menu(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        await message.answer(
            "Заметки.\n\n"
            "• Нажми «➕ Добавить заметку» и отправь текст.\n"
            "• «📄 Список заметок» — показать последние 20 (для удаления — команда `/delnote N`).",
            reply_markup=notes_kb
        )

    @dp.message(F.text == "➕ Добавить заметку")
    async def ask_note(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        await message.answer("Отправь текст заметки одним сообщением.")

    # ловим любое следующее сообщение в разделе — добавляем заметку
    @dp.message(F.text & ~F.text.in_({"🗒 Мои заметки", "➕ Добавить заметку", "📄 Список заметок", "⬅️ В меню"}))
    async def save_note(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        # простая эвристика: если недавно просили добавить — просто добавим; иначе не мешаем другим разделам
        # здесь всегда добавляем, чтобы не усложнять FSM
        text = message.text.strip()
        if not text:
            return
        note_id = await _add_note(message.from_user.id, text)
        await message.reply(f"✅ Заметка сохранена (id: `{note_id}`)", parse_mode="Markdown", reply_markup=notes_kb)

    @dp.message(F.text == "📄 Список заметок")
    async def list_notes(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        items = await _list_notes(message.from_user.id, limit=20)
        if not items:
            await message.answer("Пока нет заметок.", reply_markup=notes_kb); return

        lines = []
        for i, it in enumerate(items, start=1):
            dt = it["created_at"]
            try:
                dt_str = dt.astimezone().strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt_str = str(dt)
            # первые ~80 символов
            preview = (it.get("text") or "")[:80]
            lines.append(f"{i}. [{dt_str}] {preview}")
        lines.append("\nУдалить: `/delnote N` (номер из списка)")
        await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=notes_kb)

    @dp.message(Command("delnote"))
    async def del_note_cmd(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].isdigit():
            await message.reply("Использование: `/delnote N` — номер из последнего списка.", parse_mode="Markdown"); return
        ok = await _delete_note(message.from_user.id, int(parts[1]))
        await message.reply("🗑 Удалено." if ok else "Не найден такой номер.", reply_markup=notes_kb)
