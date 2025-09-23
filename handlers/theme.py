from aiogram import Router
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from keyboards import main_menu
from services.tarot_ai import draw_cards, gpt_make_prediction

router = Router()

class ThemeChoice(StatesGroup):
    choosing_theme = State()
    choosing_spread = State()

themes_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Любовь"), KeyboardButton(text="Работа")],
        [KeyboardButton(text="Судьба"), KeyboardButton(text="Саморазвитие")],
        [KeyboardButton(text="🔙 Назад"), KeyboardButton(text="🔙 В меню")]
    ],
    resize_keyboard=True
)

spreads_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Три карты"), KeyboardButton(text="Подкова"), KeyboardButton(text="Алхимик")],
        [KeyboardButton(text="🔙 Назад"), KeyboardButton(text="🔙 В меню")]
    ],
    resize_keyboard=True
)

@router.message(lambda msg: msg.text == "🗂 Выбрать тему")
async def start_theme_choice(message: Message, state: FSMContext):
    await message.answer("📌 Выберите тему предсказания:", reply_markup=themes_kb)
    await state.set_state(ThemeChoice.choosing_theme)

@router.message(ThemeChoice.choosing_theme)
async def process_theme(message: Message, state: FSMContext):
    theme = message.text
    if theme == "🔙 В меню":
        await state.clear()
        await message.answer("📋 Главное меню:", reply_markup=main_menu)
        return
    elif theme == "🔙 Назад":
        await state.clear()
        await message.answer("📋 Главное меню:", reply_markup=main_menu)
        return

    await state.update_data(theme=theme, prev_state=ThemeChoice.choosing_theme)
    await message.answer(f"✅ Тема выбрана: {theme}\nТеперь выберите расклад:", reply_markup=spreads_kb)
    await state.set_state(ThemeChoice.choosing_spread)

@router.message(ThemeChoice.choosing_spread)
async def process_spread(message: Message, state: FSMContext):
    spread = message.text
    if spread == "🔙 В меню":
        await state.clear()
        await message.answer("📋 Главное меню:", reply_markup=main_menu)
        return
    elif spread == "🔙 Назад":
        user_data = await state.get_data()
        await message.answer("📌 Выберите тему предсказания:", reply_markup=themes_kb)
        await state.set_state(ThemeChoice.choosing_theme)
        return

    user_data = await state.get_data()
    theme = user_data.get("theme")

    spread_cards_count = {"Три карты": 3, "Подкова": 5, "Алхимик": 7}
    num_cards = spread_cards_count.get(spread, 3)
    selected_cards = draw_cards(num_cards)
    cards_list = ", ".join([card["name"] for card in selected_cards])

    await message.answer(
        f"📌 Тема: {theme}\n"
        f"🎴 Расклад: {spread}\n"
        f"🃏 Карты: {cards_list}\n\n"
        f"🔮 Делаю толкование..."
    )

    prediction = await gpt_make_prediction(
        question=f"Предсказание на тему '{theme}'",
        theme=theme,
        spread=spread,
        cards_list=cards_list
    )

    await message.answer(prediction)
    await state.clear()
    await message.answer("📋 Главное меню:", reply_markup=main_menu)