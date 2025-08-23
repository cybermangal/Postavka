from aiogram import types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.filters import StateFilter  # 👈 добавлено

# Клавиатура раздела калькулятора
calc_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⬅️ В меню")],
    ],
    resize_keyboard=True,
)

class CalcFSM(StatesGroup):
    waiting_for_order = State()
    waiting_for_vendor = State()

def register_calc_handlers(dp, is_authorized, refuse):

    @dp.message(StateFilter('*'), F.text == "📊 Калькулятор")  # 👈 работает из любого состояния
    async def calc_start(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        await message.answer(
            "Введите сумму заказа с пометкой НДС/БНДС:\n\n"
            "Например:\n"
            "`50000 бндс` — без НДС\n"
            "`50000 ндс` — с НДС\n\n"
            "(/cancel для отмены)", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        await state.set_state(CalcFSM.waiting_for_order)

    @dp.message(CalcFSM.waiting_for_order)
    async def get_order(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        if (message.text or "").lower() == "/cancel":
            await state.clear()
            await message.answer("Отменено.", reply_markup=calc_kb)
            return

        try:
            parts = message.text.replace(",", ".").split()
            if len(parts) != 2 or parts[1].lower() not in ("ндс", "бндс"):
                raise ValueError
            order_value = float(parts[0])
            order_type = parts[1].lower()
        except Exception:
            await message.answer(
                "❗️ Введите сумму заказа и укажите 'ндс' или 'бндс', например: `55000 бндс`",
                parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            return

        await state.update_data(order_value=order_value, order_type=order_type)
        await message.answer(
            "Теперь введите сумму для исполнителя с пометкой НДС/БНДС:\n\n"
            "Например:\n"
            "`45000 бндс` — без НДС\n"
            "`45000 ндс` — с НДС\n\n"
            "(/cancel для отмены)", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        await state.set_state(CalcFSM.waiting_for_vendor)

    @dp.message(CalcFSM.waiting_for_vendor)
    async def get_vendor(message: types.Message, state: FSMContext):
        if not is_authorized(message.from_user.id):
            await refuse(message)
            return
        if (message.text or "").lower() == "/cancel":
            await state.clear()
            await message.answer("Отменено.", reply_markup=calc_kb)
            return

        try:
            parts = message.text.replace(",", ".").split()
            if len(parts) != 2 or parts[1].lower() not in ("ндс", "бндс"):
                raise ValueError
            vendor_value = float(parts[0])
            vendor_type = parts[1].lower()
        except Exception:
            await message.answer(
                "❗️ Введите сумму для исполнителя и укажите 'ндс' или 'бндс', например: `40000 бндс`",
                parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            return

        data = await state.get_data()
        order_value = data["order_value"]
        order_type = data["order_type"]

        if order_type == vendor_type:
            net_order = order_value
            net_vendor = vendor_value
            profit = (net_order - net_vendor) * 0.77
            markup_type = "A"
        elif order_type == "ндс" and vendor_type == "бндс":
            net_order = order_value / 1.2
            net_vendor = vendor_value
            profit = (net_order - net_vendor) * 0.88
            markup_type = "B"
        elif order_type == "бндс" and vendor_type == "ндс":
            net_order = order_value
            net_vendor = vendor_value / 1.2
            profit = (net_order - net_vendor) * 0.88
            markup_type = "C"
        else:
            await message.answer("Ошибка: что-то пошло не так с типами. Попробуйте ещё раз.", reply_markup=calc_kb)
            await state.clear()
            return

        try:
            margin = (profit / net_order) * 100 if net_order else 0
        except ZeroDivisionError:
            margin = 0

        profit = round(profit, 2)
        margin = round(margin, 2)
        net_order = round(net_order, 2)
        net_vendor = round(net_vendor, 2)

        formula_label = {
            "A": "Оба 'с НДС' или оба 'без НДС'",
            "B": "Заказ с НДС, Исполнитель без НДС",
            "C": "Заказ без НДС, Исполнитель с НДС"
        }

        await message.answer(
            f"📊 <b>Калькулятор маржинальности</b>\n"
            f"<i>{formula_label.get(markup_type)}</i>\n\n"
            f"<b>Заказ:</b> {net_order}\n"
            f"<b>Исполнитель:</b> {net_vendor}\n"
            f"<b>Прибыль:</b> {profit}\n"
            f"<b>Рентабельность:</b> {margin}%\n",
            parse_mode="HTML", reply_markup=calc_kb
        )
        await state.clear()
