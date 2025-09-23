# handlers/navigation.py
from aiogram import Router
from aiogram.types import Message
from keyboards import main_menu, theme_keyboard, spread_keyboard
from handlers.theme_spread import ThemeChoice
from aiogram.fsm.context import FSMContext

router = Router()

# --- Кнопка "⬅️ В меню" ---
@router.message(lambda m: m.text == "⬅️ В меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔙 Главное меню:", reply_markup=main_menu)

# --- Кнопка "🔙 Назад" (возврат в тему или расклад) ---
@router.message(lambda m: m.text == "🔙 Назад")
async def go_back(message: Message, state: FSMContext):
    state_name = await state.get_state()
    if state_name == ThemeChoice.spread:  # из раскладов → в темы
        await state.set_state(ThemeChoice.theme)
        await message.answer("Вы вернулись к выбору темы:", reply_markup=theme_keyboard)
    elif state_name == ThemeChoice.theme:  # из тем → в меню
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_menu)
    else:  # если без состояния
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_menu)
