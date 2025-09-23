from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🗂 Выбрать тему"), KeyboardButton(text="📝 Свой вопрос")],
        [KeyboardButton(text="🎁 Промокод"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🤝 Пригласить друга"), KeyboardButton(text="🛒 Купить сообщения")],
    ],
    resize_keyboard=True
)

theme_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Любовь"), KeyboardButton(text="Работа")],
        [KeyboardButton(text="Судьба"), KeyboardButton(text="Саморазвитие")],
        [KeyboardButton(text="⬅️ В меню")]
    ],
    resize_keyboard=True
)

spread_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Три карты"), KeyboardButton(text="Подкова")],
        [KeyboardButton(text="Алхимик")],
        [KeyboardButton(text="🔙 Назад"), KeyboardButton(text="⬅️ В меню")]
    ],
    resize_keyboard=True
)

custom_question_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⬅️ В меню")]
    ],
    resize_keyboard=True
)