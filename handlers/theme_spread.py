# handlers/theme_spread.py
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from services.billing import spend_one_credit
from services.tarot_ai import draw_cards, gpt_make_prediction
from db import SessionLocal, models
from keyboards import theme_keyboard, spread_keyboard, main_menu

router = Router()


class ThemeChoice(StatesGroup):
    choosing_theme = State()
    choosing_spread = State()


@router.message(F.text == "🗂 Выбрать тему")
async def choose_theme(message: Message, state: FSMContext):
    await message.answer("Выберите тему:", reply_markup=theme_keyboard)
    await state.set_state(ThemeChoice.choosing_theme)


# === choosing_theme ===
@router.message(ThemeChoice.choosing_theme, F.text == "Назад")
async def back_to_main_from_theme(message: Message, state: FSMContext):
    await message.answer("Возвращаемся в главное меню.", reply_markup=main_menu)
    await state.clear()


@router.message(ThemeChoice.choosing_theme, F.text == "В меню")
async def to_main_menu_from_theme(message: Message, state: FSMContext):
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu)
    await state.clear()


@router.message(ThemeChoice.choosing_theme, F.text.not_in(["Назад", "В меню"]))
async def process_theme_choice(message: Message, state: FSMContext):
    theme = message.text.strip()
    await state.update_data(theme=theme)
    await message.answer("Выберите расклад:", reply_markup=spread_keyboard)
    await state.set_state(ThemeChoice.choosing_spread)


# === choosing_spread ===
@router.message(ThemeChoice.choosing_spread, F.text == "🔙 Назад")
async def back_to_theme(message: Message, state: FSMContext):
    await message.answer("Выберите тему:", reply_markup=theme_keyboard)
    await state.set_state(ThemeChoice.choosing_theme)


@router.message(ThemeChoice.choosing_spread, F.text == "⬅️ В меню")
async def to_main_menu_from_spread(message: Message, state: FSMContext):
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu)
    await state.clear()


@router.message(ThemeChoice.choosing_spread, F.text.not_in(["🔙 Назад", "⬅️ В меню"]))
async def process_spread_choice(message: Message, state: FSMContext):
    data = await state.get_data()
    theme = data.get("theme")
    spread = message.text.strip()

    # Проверяем баланс
    ok = await spend_one_credit(message.from_user.id)
    if not ok:
        await message.answer("❌ У вас нет доступных сообщений. Пополните баланс 🛒", reply_markup=main_menu)
        await state.clear()
        return

    # Выбираем количество карт по типу расклада
    if spread == "Три карты":
        cards = draw_cards(3)
    elif spread == "Подкова":
        cards = draw_cards(7)
    elif spread == "Алхимик":
        cards = draw_cards(4)
    else:
        await message.answer("Неизвестный расклад.", reply_markup=main_menu)
        await state.clear()
        return

    prediction = await gpt_make_prediction(f"Тема: {theme}", cards)

    # Лог в БД
    async with SessionLocal() as session:
        log = models.SpreadLog(
            user_id=message.from_user.id,
            theme=theme,
            spread=spread,
            cards={"cards": cards},
            cost=1,
        )
        session.add(log)
        await session.commit()

    await message.answer(prediction, reply_markup=main_menu)
    await state.clear()
