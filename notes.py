from aiogram import types, F
from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import asyncio

# --- Хранилище заметок ---
user_notes = {}

# --- Тексты всех кнопок меню, чтобы использовать для проверки ---
button_texts = [
    "➕ Добавить заметку",
    "⏰ Заметка с напоминанием",
    "📄 Посмотреть заметки",
    "🗑 Удалить заметку",
    "⬅️ В меню"
]

# --- Клавиатуры для раздела ---
notes_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить заметку")],
        [KeyboardButton(text="⏰ Заметка с напоминанием")],
        [KeyboardButton(text="📄 Посмотреть заметки")],
        [KeyboardButton(text="🗑 Удалить заметку")],
        [KeyboardButton(text="⬅️ В меню")],
    ],
    resize_keyboard=True,
)

# --- FSM состояния ---
class NotesFSM(StatesGroup):
    waiting_for_note_text = State()
    waiting_for_reminder_text = State()
    waiting_for_reminder_date = State()
    waiting_for_reminder_time = State()
    waiting_for_reminder_custom_date = State()
    waiting_for_reminder_custom_time = State()
    waiting_for_delete_number = State()

def register_notes_handlers(dp, is_authorized, refuse):

    @dp.message(F.text == "🗒 Мои заметки")
    async def notes_menu(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        await message.answer("Что сделать с заметками?", reply_markup=notes_kb)

    @dp.message(F.text == "⬅️ В меню")
    async def to_main_menu(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        await state.clear()
        await message.answer("Главное меню:", reply_markup=message.bot.main_kb)

    @dp.message(F.text == "➕ Добавить заметку")
    async def add_note_start(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        # Скрываем клавиатуру мгновенно!
        await message.answer("Напиши текст заметки (или /cancel):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(NotesFSM.waiting_for_note_text)

    @dp.message(NotesFSM.waiting_for_note_text)
    async def save_note(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return

        # Не даём записывать в заметку текст с кнопки
        if message.text in button_texts:
            await message.answer(
                "Сначала напиши текст заметки или /cancel.\n"
                "Чтобы выйти — напиши /cancel.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        if message.text.lower() == "/cancel":
            await state.clear()
            await message.answer("Отменено.", reply_markup=notes_kb)
            return

        user_id = message.from_user.id
        note = message.text
        user_notes.setdefault(user_id, []).append(note)
        await state.clear()
        await message.answer("Заметка сохранена!", reply_markup=notes_kb)

    @dp.message(F.text == "⏰ Заметка с напоминанием")
    async def reminder_note_start(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        await message.answer("Введи текст напоминания (или /cancel):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(NotesFSM.waiting_for_reminder_text)

    @dp.message(NotesFSM.waiting_for_reminder_text)
    async def reminder_note_text(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return

        # Не даём записывать кнопки
        if message.text in button_texts:
            await message.answer(
                "Сначала напиши текст напоминания или /cancel.\n"
                "Чтобы выйти — напиши /cancel.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        if message.text.lower() == "/cancel":
            await state.clear()
            await message.answer("Отменено.", reply_markup=notes_kb)
            return
        await state.update_data(reminder_text=message.text)
        # Кнопки для выбора даты
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Сегодня", callback_data="reminder_date_today")],
            [InlineKeyboardButton(text="Завтра", callback_data="reminder_date_tomorrow")],
            [InlineKeyboardButton(text="Другая дата", callback_data="reminder_date_other")]
        ])
        await message.answer("Выбери дату:", reply_markup=kb)
        await state.set_state(NotesFSM.waiting_for_reminder_date)

    @dp.callback_query(F.data.startswith("reminder_date_"))
    async def reminder_choose_date(callback: types.CallbackQuery, state: FSMContext):
        if not is_authorized(callback.from_user.id):
            await refuse(callback.message)
            return
        data = callback.data
        now = datetime.now()
        if data == "reminder_date_today":
            await state.update_data(reminder_date=now.date())
        elif data == "reminder_date_tomorrow":
            await state.update_data(reminder_date=(now + timedelta(days=1)).date())
        elif data == "reminder_date_other":
            await callback.message.answer("Введи дату в формате ДД.ММ.ГГГГ или /cancel:")
            await state.set_state(NotesFSM.waiting_for_reminder_custom_date)
            await callback.answer()
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="09:00", callback_data="reminder_time_09:00"),
             InlineKeyboardButton(text="12:00", callback_data="reminder_time_12:00")],
            [InlineKeyboardButton(text="15:00", callback_data="reminder_time_15:00"),
             InlineKeyboardButton(text="18:00", callback_data="reminder_time_18:00")],
            [InlineKeyboardButton(text="21:00", callback_data="reminder_time_21:00")],
            [InlineKeyboardButton(text="Другое время", callback_data="reminder_time_other")]
        ])
        await callback.message.answer("Выбери время:", reply_markup=kb)
        await state.set_state(NotesFSM.waiting_for_reminder_time)
        await callback.answer()

    @dp.message(NotesFSM.waiting_for_reminder_custom_date)
    async def reminder_custom_date(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        if message.text.lower() == "/cancel":
            await state.clear()
            await message.answer("Отменено.", reply_markup=notes_kb)
            return
        try:
            date = datetime.strptime(message.text, "%d.%m.%Y").date()
            await state.update_data(reminder_date=date)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="09:00", callback_data="reminder_time_09:00"),
                 InlineKeyboardButton(text="12:00", callback_data="reminder_time_12:00")],
                [InlineKeyboardButton(text="15:00", callback_data="reminder_time_15:00"),
                 InlineKeyboardButton(text="18:00", callback_data="reminder_time_18:00")],
                [InlineKeyboardButton(text="21:00", callback_data="reminder_time_21:00")],
                [InlineKeyboardButton(text="Другое время", callback_data="reminder_time_other")]
            ])
            await message.answer("Выбери время:", reply_markup=kb)
            await state.set_state(NotesFSM.waiting_for_reminder_time)
        except Exception:
            await message.answer("Неверный формат даты! Пример: 15.08.2025 или /cancel")

    @dp.callback_query(F.data.startswith("reminder_time_"))
    async def reminder_choose_time(callback: types.CallbackQuery, state: FSMContext):
        if not is_authorized(callback.from_user.id):
            await refuse(callback.message)
            return
        data = callback.data
        if data == "reminder_time_other":
            await callback.message.answer("Введи время в формате ЧЧ:ММ (например, 17:30) или /cancel:")
            await state.set_state(NotesFSM.waiting_for_reminder_custom_time)
            await callback.answer()
            return
        # стандартное время
        time_str = data.replace("reminder_time_", "")
        await state.update_data(reminder_time=time_str)
        await create_reminder(callback.message, state)
        await callback.answer()

    @dp.message(NotesFSM.waiting_for_reminder_custom_time)
    async def reminder_custom_time(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return

        if message.text in button_texts:
            await message.answer(
                "Сначала напиши время вручную или /cancel.\n"
                "Чтобы выйти — напиши /cancel.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        if message.text.lower() == "/cancel":
            await state.clear()
            await message.answer("Отменено.", reply_markup=notes_kb)
            return
        try:
            t = datetime.strptime(message.text, "%H:%M").time()
            await state.update_data(reminder_time=message.text)
            await create_reminder(message, state)
        except Exception:
            await message.answer("Неверный формат! Введи время как 09:30 или /cancel")

    async def create_reminder(message_or_callback, state: FSMContext):
        data = await state.get_data()
        reminder_text = data.get("reminder_text")
        reminder_date = data.get("reminder_date")
        reminder_time = data.get("reminder_time")
        user_id = message_or_callback.from_user.id
        try:
            dt_str = f"{reminder_date} {reminder_time}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            now = datetime.now()
            delay = (dt - now).total_seconds()
            if delay <= 0:
                await message_or_callback.answer("Дата и время в прошлом! Попробуй снова.", reply_markup=notes_kb)
                await state.clear()
                return
            user_notes.setdefault(user_id, []).append(f"⏰ {reminder_text} [{dt.strftime('%d.%m.%Y %H:%M')}]")
            await message_or_callback.answer(
                f"Напоминание сохранено! Я напомню: {dt.strftime('%d.%m.%Y %H:%M')}", reply_markup=notes_kb
            )
            asyncio.create_task(send_reminder_later(message_or_callback.bot, user_id, reminder_text, dt))
        except Exception:
            await message_or_callback.answer("Ошибка в дате или времени.", reply_markup=notes_kb)
        await state.clear()

    async def send_reminder_later(bot, user_id, text, dt):
        now = datetime.now()
        delay = (dt - now).total_seconds()
        await asyncio.sleep(delay)
        try:
            await bot.send_message(user_id, f"🔔 Напоминание!\n{text}")
        except Exception:
            pass

    @dp.message(F.text == "📄 Посмотреть заметки")
    async def show_notes(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        user_id = message.from_user.id
        notes = user_notes.get(user_id, [])
        if not notes:
            await message.answer("У тебя пока нет заметок.", reply_markup=notes_kb)
        else:
            txt = "\n\n".join([f"{i+1}. {n}" for i, n in enumerate(notes)])
            await message.answer(f"Твои заметки:\n\n{txt}", reply_markup=notes_kb)

    @dp.message(F.text == "🗑 Удалить заметку")
    async def delete_note_start(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        user_id = message.from_user.id
        notes = user_notes.get(user_id, [])
        if not notes:
            await message.answer("Удалять нечего, заметок нет.", reply_markup=notes_kb)
            return
        txt = "\n".join([f"{i+1}. {n[:30]}" for i, n in enumerate(notes)])
        await message.answer(f"Выбери номер заметки для удаления:\n\n{txt}\n\nИли /cancel", reply_markup=notes_kb)
        await state.set_state(NotesFSM.waiting_for_delete_number)

    @dp.message(NotesFSM.waiting_for_delete_number)
    async def confirm_delete(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        user_id = message.from_user.id
        notes = user_notes.get(user_id, [])
        if message.text.lower() == "/cancel":
            await state.clear()
            await message.answer("Отменено.", reply_markup=notes_kb)
            return
        try:
            num = int(message.text) - 1
            if 0 <= num < len(notes):
                deleted = user_notes[user_id].pop(num)
                await message.answer(f"Заметка удалена:\n{deleted}", reply_markup=notes_kb)
            else:
                await message.answer("Нет такой заметки.", reply_markup=notes_kb)
        except ValueError:
            await message.answer("Введи номер заметки.", reply_markup=notes_kb)
        await state.clear()
