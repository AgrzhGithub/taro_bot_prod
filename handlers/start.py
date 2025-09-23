# handlers/start.py
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from services.billing import (
    ensure_user,
    redeem_promocode,
    create_referral_promocode_for_user,
)
from keyboards import main_menu

router = Router()


@router.message(CommandStart())
async def start_cmd(message: Message):
    # регистрируем/обновляем юзера
    user = await ensure_user(message.from_user.id, message.from_user.username)

    # разбор deep-link кода ("/start CODE")
    args = ""
    if message.text and " " in message.text:
        args = message.text.split(maxsplit=1)[1].strip()

    hint = ""
    if args:
        # автоматическая попытка активации промокода
        ok, msg = await redeem_promocode(message.from_user.id, args)
        hint = f"\n\n{msg}"

    # создаём реферальный промокод для текущего пользователя
    await create_referral_promocode_for_user(user)

    # приветственное сообщение
    await message.answer(
        "🔮 Привет! Я Таро-бот.\n"
        "Выберите действие в меню ниже." + hint,
        reply_markup=main_menu
    )
