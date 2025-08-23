import os
from aiogram import types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile

DOC_PATH = r"C:\Users\Metalist\Desktop\1\1.docx"
DOC_NAME = "1.docx"

docs_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=DOC_NAME)],
        [KeyboardButton(text="⬅️ В меню")]
    ],
    resize_keyboard=True,
)

def register_docs_handlers(dp, is_authorized, refuse):
    @dp.message(F.text == "📁 Документы")
    async def docs_menu(message: types.Message, state=None):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return

        if not os.path.isfile(DOC_PATH):
            # используем прикреплённую к боту клавиатуру, если есть
            kb = getattr(message.bot, "main_kb", None)
            await message.answer("Файл не найден.", reply_markup=kb)
            return

        await message.answer("Нажми на кнопку, чтобы получить файл:", reply_markup=docs_kb)

    # ⬇️ Раньше здесь стояло @dp.message() — перехватывало всё подряд.
    @dp.message(F.text.in_({DOC_NAME, "⬅️ В меню"}))
    async def send_doc(message: types.Message, state=None):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return

        if message.text == DOC_NAME:
            try:
                file = FSInputFile(DOC_PATH)
                await message.answer_document(file, caption=f"📁 {DOC_NAME}", reply_markup=docs_kb)
            except Exception as e:
                await message.answer(f"Ошибка при отправке: {e}", reply_markup=docs_kb)
            return

        # Назад в меню
        kb = getattr(message.bot, "main_kb", None)
        await message.answer("Главное меню:", reply_markup=kb)
