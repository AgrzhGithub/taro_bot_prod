# handlers/billing.py
from aiogram import Router
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from services.billing import grant_credits, ensure_user, get_user_balance
from keyboards import main_menu

router = Router()

# клавиатура выбора пакета
buy_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="5 сообщений — 149₽")],
        [KeyboardButton(text="10 сообщений — 249₽")],
        [KeyboardButton(text="30 сообщений — 549₽")],
        [KeyboardButton(text="⬅️ В меню")]
    ],
    resize_keyboard=True
)

@router.message(lambda msg: msg.text == "🛒 Купить сообщения")
async def buy_start(message: Message):
    await message.answer("Выберите пакет сообщений:", reply_markup=buy_kb)

@router.message(lambda msg: msg.text in ["5 сообщений — 149₽", "10 сообщений — 249₽", "30 сообщений — 549₽"])
async def buy_package(message: Message):
    tg_id = message.from_user.id
    user = await ensure_user(tg_id, message.from_user.username)

    if message.text.startswith("5"):
        credits, price = 5, 149
    elif message.text.startswith("10"):
        credits, price = 10, 249
    else:
        credits, price = 30, 549

    # фейковая оплата — просто начисляем кредиты
    await grant_credits(user.id, credits, reason=f"fake_payment_{price}")

    balance = await get_user_balance(tg_id)
    await message.answer(
        f"✅ Оплата прошла успешно!\n"
        f"Вам начислено {credits} сообщений.\n\n"
        f"Баланс: {balance} сообщений",
        reply_markup=main_menu
    )

@router.message(lambda msg: msg.text == "⬅️ В меню")
async def back_to_menu(message: Message):
    await message.answer("🔙 Возвращаюсь в главное меню", reply_markup=main_menu)
