from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from keyboards import main_menu
from services.billing import redeem_promocode, get_user_balance, ensure_user, build_invite_link, get_pass_status

router = Router()

# Клавиатура с кнопкой "В меню"
promo_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⬅️ В меню")]
    ],
    resize_keyboard=True
)

class PromoStates(StatesGroup):
    waiting_code = State()

@router.message(F.text == "🎁 Промокод")
async def ask_promo(message: Message, state: FSMContext):
    await message.answer(
        "Введите промокод одним сообщением:",
        reply_markup=promo_keyboard
    )
    await state.set_state(PromoStates.waiting_code)

@router.message(PromoStates.waiting_code)
async def redeem_promo(message: Message, state: FSMContext):
    code = (message.text or "").strip()
    if code == "⬅️ В меню":
        await state.clear()
        await message.answer("📋 Главное меню:", reply_markup=main_menu)
        return

    ok, info = await redeem_promocode(message.from_user.id, code)
    if ok:
        balance = await get_user_balance(message.from_user.id)
        await message.answer(
            f"{info}\n\nВаш баланс: {balance} сообщений",
            reply_markup=main_menu
        )
    else:
        await message.answer(info, reply_markup=promo_keyboard)
    await state.clear()

@router.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = await ensure_user(message.from_user.id, message.from_user.username)
    balance = await get_user_balance(message.from_user.id)
    link = build_invite_link(user.invite_code)
    pass_line = "Подписка не активна"
    active, until = await get_pass_status(message.from_user.id)
    if active:
        pass_line = f"Подписка активна до {until:%d.%m.%Y}"
    await message.answer(
        "👤 Профиль\n"
        f"ID: {user.tg_id}\n"
        f"Баланс: {balance} сообщений\n"
        f"🎫 {pass_line}\n\n"
        f"Ваш реферальный код: {user.invite_code}\n"
        f"Ссылка для приглашений:\n{link}",
        reply_markup=main_menu
    )

@router.message(F.text == "🤝 Пригласить друга")
async def invite(message: Message):
    user = await ensure_user(message.from_user.id, message.from_user.username)
    link = build_invite_link(user.invite_code)
    await message.answer(
        "Поделитесь этой ссылкой. Когда друг активирует промокод, вы оба получите бонус 🎉\n\n"
        f"{link}",
        reply_markup=main_menu
    )
