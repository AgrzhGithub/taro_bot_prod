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
         InlineKeyboardButton(text="Самопознание", callback_data="theme:Саморазвитие")],
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
        [InlineKeyboardButton(text="5 сообщений — 80₽", callback_data="buy:credits:5:8000")],
        [InlineKeyboardButton(text="10 сообщений — 119₽", callback_data="buy:credits:10:11900")],
        [InlineKeyboardButton(text="30 сообщений — 199₽", callback_data="buy:credits:30:19900")],
        [InlineKeyboardButton(text="Подписка (30 дней) — 299₽", callback_data="buy:pass30:29900")],
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

def promo_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="menu:promo")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ])

def scenario_inline(theme_id: str, scenarios: list) -> InlineKeyboardMarkup:
    # scenarios — список объектов с полями .id и .title
    rows = []
    for s in scenarios:
        rows.append([InlineKeyboardButton(text=s.title, callback_data=f"scen:select:{theme_id}:{s.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ К темам", callback_data="nav:theme")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def advice_inline_limits(allow_one: bool = True, allow_three: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if allow_one:
        rows.append([InlineKeyboardButton(text="🧭 Обычный совет (1 карта)", callback_data="advice:1")])
    if allow_three:
        rows.append([InlineKeyboardButton(text="🔮 Расширенный совет (3 карты)", callback_data="advice:3")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def advice_buy_inline(amount_kopecs: int) -> InlineKeyboardMarkup:
    rub = amount_kopecs // 100
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Купить совет — {rub}₽", callback_data=f"buy:advice1:{amount_kopecs}")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ])
