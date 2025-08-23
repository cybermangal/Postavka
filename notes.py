# notes.py — пользовательские заметки с MongoDB (без всеядных хэндлеров)
from datetime import datetime, timezone
from typing import List

from aiogram import types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.filters import StateFilter

from db import notes as col

# Клавиатура раздела заметок
notes_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить заметку")],
        [KeyboardButton(text="📄 Список заметок")],
        [KeyboardButton(text="⬅️ В меню")],
    ],
    resize_keyboard=True,
)

# FSM: ждём текст заметки только после явного запроса
class NotesFSM(StatesGroup):
    waiting_for_text = State()

async def _add_note(user_id: int, text: str) -> str:
    doc = {"user_id": int(user_id), "text": text, "created_at": datetime.now(timezone.utc)}
    res = await col.insert_one(doc)
    return str(res.inserted_id)

async def _list_notes(user_id: int, limit: int = 20) -> List[dict]:
    cur = col.find({"user_id": int(user_id)}).sort("created_at", -1).limit(limit)
    return [doc async for doc in cur]

async def _delete_note_by_index(user_id: int, idx: int) -> bool:
    items = await _list_notes(user_id, limit=50)
    if 1 <= idx <= len(items):
        target = items[idx - 1]
        res = await col.delete_one({"_id": target["_id"], "user_id": int(user_id)})
        return res.deleted_count == 1
    return False

def register_notes_handlers(dp, is_authorized, refuse):

    # Вход в раздел: работает из любого состояния и ничего не перехватывает дальше
    @dp.message(StateFilter('*'), F.text == "🗒 Мои заметки")
    async def notes_menu(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        await state.clear()
        await message.answer(
            "Заметки.\n\n"
            "• Нажми «➕ Добавить заметку» и отправь текст одной фразой.\n"
            "• «📄 Список заметок» — показать последние 20 (удаление: `/delnote N`).",
            reply_markup=notes_kb
        )

    # Явный запрос на добавление — ставим состояние ожидания текста
    @dp.message(StateFilter('*'), F.text == "➕ Добавить заметку")
    async def ask_note(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        await state.set_state(NotesFSM.waiting_for_text)
        await message.answer(
            "Отправь текст заметки одним сообщением.\n(/cancel — отмена)",
            reply_markup=ReplyKeyboardRemove()
        )

    # Принятие текста заметки — ТОЛЬКО в состоянии waiting_for_text
    @dp.message(NotesFSM.waiting_for_text, F.text)
    async def save_note(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message); return

        txt = (message.text or "").strip()
        if txt.lower() in {"/cancel", "отмена"}:
            await state.clear()
            await message.answer("Отменено.", reply_markup=notes_kb)
            return

        if not txt:
            await message.reply("Пустую заметку не сохраняю. Напиши текст или /cancel.")
            return

        note_id = await _add_note(message.from_user.id, txt)
        await state.clear()
        await message.reply(f"✅ Заметка сохранена (id: `{note_id}`)", parse_mode="Markdown", reply_markup=notes_kb)

    # Список заметок — из любого состояния, перед показом очищаем состояние
    @dp.message(StateFilter('*'), F.text == "📄 Список заметок")
    async def list_notes(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        await state.clear()

        items = await _list_notes(message.from_user.id, limit=20)
        if not items:
            await message.answer("Пока нет заметок.", reply_markup=notes_kb); return

        lines = []
        for i, it in enumerate(items, start=1):
            dt = it.get("created_at")
            try:
                dt_str = dt.astimezone().strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt_str = str(dt)
            preview = (it.get("text") or "").replace("\n", " ")[:120]
            lines.append(f"{i}. [{dt_str}] {preview}")
        lines.append("\nУдалить: `/delnote N` (номер из списка)")
        await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=notes_kb)

    # Удаление по номеру из списка
    @dp.message(Command("delnote"))
    async def del_note_cmd(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].isdigit():
            await message.reply("Использование: `/delnote N` — номер из списка.", parse_mode="Markdown")
            return
        ok = await _delete_note_by_index(message.from_user.id, int(parts[1]))
        await message.reply("🗑 Удалено." if ok else "Не найден такой номер.", reply_markup=notes_kb)

    # Назад в меню — из любого состояния
    @dp.message(StateFilter('*'), F.text == "⬅️ В меню")
    async def back_to_menu(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        await state.clear()
        kb = getattr(message.bot, "main_kb", None)
        await message.answer("Главное меню:", reply_markup=kb)
