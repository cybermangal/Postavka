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
            await message.answer("Файл не найден.", reply_markup=message.bot.main_kb)
            return

        await message.answer("Нажми на кнопку, чтобы получить файл:", reply_markup=docs_kb)

    @dp.message()
    async def send_doc(message: types.Message, state=None):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return

        if message.text == DOC_NAME:
            try:
                file = FSInputFile(DOC_PATH)
                await message.answer_document(file, caption="📁 1.docx", reply_markup=docs_kb)
            except Exception as e:
                await message.answer(f"Ошибка при отправке: {e}", reply_markup=docs_kb)
            return

        if message.text == "⬅️ В меню":
            await message.answer("Главное меню:", reply_markup=message.bot.main_kb)
            return
