# keyboards_inline.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗂 Выбрать тему", callback_data="menu:theme")],
        [InlineKeyboardButton(text="📝 Свой вопрос",  callback_data="menu:custom")],
        [InlineKeyboardButton(text="🗓 Карта дня",    callback_data="menu:daily")],
        [InlineKeyboardButton(text="👤 Профиль",     callback_data="menu:profile"),
         InlineKeyboardButton(text="🛒 Купить сообщения", callback_data="menu:buy")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
        [InlineKeyboardButton(text="✉️ Обратная связь", callback_data="menu:feedback")],
    ])

def theme_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Любовь", callback_data="theme:Любовь"),
         InlineKeyboardButton(text="Работа", callback_data="theme:Работа")],
        [InlineKeyboardButton(text="Судьба", callback_data="theme:Судьба"),
         InlineKeyboardButton(text="Саморазвитие", callback_data="theme:Саморазвитие")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ])

def spread_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Три карты", callback_data="spread:Три карты"),
         InlineKeyboardButton(text="Подкова", callback_data="spread:Подкова")],
        [InlineKeyboardButton(text="Алхимик", callback_data="spread:Алхимик")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="nav:theme"),
         InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ])

def buy_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="5 сообщений — 149₽", callback_data="buy:5:14900")],
        [InlineKeyboardButton(text="10 сообщений — 399₽", callback_data="buy:10:30000")],
        [InlineKeyboardButton(text="30 сообщений — 599₽", callback_data="buy:30:59900")],
        [InlineKeyboardButton(text="Подписка (30 дней) — 599₽", callback_data="buy:pass30:59900")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ])

def back_to_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")]
    ])

def daily_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗓 Подписаться на карту дня", callback_data="daily:on")],
        [InlineKeyboardButton(text="❌ Отписаться от карты дня", callback_data="daily:off")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ])

