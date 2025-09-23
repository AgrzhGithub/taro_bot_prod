# handlers/profile.py
from aiogram import Router
from aiogram.types import Message
from services.billing import get_user_balance
from keyboards import main_menu

router = Router()

@router.message(lambda m: m.text == "👤 Профиль")
async def profile(message: Message):
    balance = await get_user_balance(message.from_user.id)
    await message.answer(
        f"👤 Ваш профиль\n\n💰 Баланс: {balance} сообщений",
        reply_markup=main_menu
    )
