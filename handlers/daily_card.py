# handlers/daily_card.py
import os
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from services.daily import (
    subscribe_daily, unsubscribe_daily, resolve_card_image,
    draw_random_card
)
from services.tarot_ai import gpt_make_prediction

router = Router()

# ---------------------------
# Локальные клавиатуры
# ---------------------------
def _main_menu_kb():
    # пытаемся использовать ваше основное инлайн-меню, если есть
    try:
        from keyboards_inline import main_menu_inline
        return main_menu_inline()
    except Exception:
        # fallback
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")]
            ]
        )

def _daily_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗓 Подписаться на карту дня", callback_data="daily:on")],
        [InlineKeyboardButton(text="⏰ Выбрать время", callback_data="daily:time")],
        [InlineKeyboardButton(text="❌ Отписаться", callback_data="daily:off")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ])

def _daily_time_kb():
    # Набор популярных часов. Можешь отредактировать под свою аудиторию.
    rows = [
        [8, 9, 10],
        [12, 18, 21],
        [7, 11, 20]
    ]
    kb = []
    for row in rows:
        kb.append([
            InlineKeyboardButton(text=f"{h:02d}:00", callback_data=f"daily:time:{h}") for h in row
        ])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:daily")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ---------------------------
# Безопасный edit_text
# ---------------------------
async def _safe_edit(msg, text: str, **kwargs):
    try:
        return await msg.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return msg
        raise

# ---------------------------
# Inline-управление подпиской
# ---------------------------
@router.callback_query(F.data == "menu:daily")
async def daily_menu(cb: CallbackQuery):
    await cb.answer()
    await _safe_edit(cb.message, "🗓 Управление подпиской на «Карту дня»:", reply_markup=_daily_menu_kb())

@router.callback_query(F.data == "daily:on")
async def daily_on_cb(cb: CallbackQuery):
    await cb.answer()
    ok, msg = await subscribe_daily(cb.from_user.id)
    await _safe_edit(cb.message, ("✅ " if ok else "⚠️ ") + msg, reply_markup=_main_menu_kb())

@router.callback_query(F.data == "daily:off")
async def daily_off_cb(cb: CallbackQuery):
    await cb.answer()
    ok, msg = await unsubscribe_daily(cb.from_user.id)
    await _safe_edit(cb.message, ("✅ " if ok else "⚠️ ") + msg, reply_markup=_main_menu_kb())

@router.callback_query(F.data == "daily:time")
async def daily_time_menu(cb: CallbackQuery):
    await cb.answer()
    await _safe_edit(cb.message, "⏰ Выберите время, когда присылать «Карту дня»:", reply_markup=_daily_time_kb())

@router.callback_query(F.data.startswith("daily:time:"))
async def daily_time_pick(cb: CallbackQuery):
    await cb.answer()
    try:
        hour = int(cb.data.split(":")[2])
    except Exception:
        hour = 9
    ok, msg = await subscribe_daily(cb.from_user.id, hour=hour, tz="Europe/Moscow")
    # После выбора времени вернёмся в меню «Карта дня»
    await _safe_edit(cb.message, ("✅ " if ok else "⚠️ ") + msg, reply_markup=_daily_menu_kb())

# ---------------------------
# Команды (оставлены для совместимости)
# ---------------------------
@router.message(Command("card_daily_on"))
async def daily_on_cmd(message: Message):
    ok, msg = await subscribe_daily(message.from_user.id)
    await message.answer(("✅ " if ok else "⚠️ ") + msg, reply_markup=_main_menu_kb())

@router.message(Command("card_daily_off"))
async def daily_off_cmd(message: Message):
    ok, msg = await unsubscribe_daily(message.from_user.id)
    await message.answer(("✅ " if ok else "⚠️ ") + msg, reply_markup=_main_menu_kb())

@router.message(Command("card_daily_time"))
async def daily_time_cmd(message: Message):
    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Формат: /card_daily_time <час 0..23> [таймзона]\nНапр.: /card_daily_time 9 Europe/Moscow")
        return
    hour = parts[1]
    tz = parts[2] if len(parts) == 3 else "Europe/Moscow"
    try:
        h = int(hour)
    except Exception:
        await message.answer("Час должен быть числом 0..23")
        return
    ok, msg = await subscribe_daily(message.from_user.id, hour=h, tz=tz)
    await message.answer(("✅ " if ok else "⚠️ ") + msg, reply_markup=_main_menu_kb())

# ---------------------------
# Отправка «Карты дня»
# ---------------------------
async def send_card_of_day(bot, chat_id: int):
    """
    Отправить карту дня с фото (если найдено изображение).
    Карта берётся из data/tarot_cards.json через draw_random_card().
    """
    card = draw_random_card()
    name = card.get("name") or card.get("title") or str(card)

    # Получаем толкование
    try:
        interpretation = await gpt_make_prediction(
            question="Карта дня",
            theme="Карта дня",
            spread="one-card",
            cards_list=name,
        )
    except Exception:
        interpretation = f"Ваша карта дня: {name}.\n(Толкование временно недоступно.)"

    caption = f"🗓 Карта дня\n\n🃏 {name}\n\n{interpretation}"

    img_path = resolve_card_image(name)
    if img_path and os.path.exists(img_path):
        await bot.send_photo(chat_id, FSInputFile(img_path), caption=caption)
    else:
        await bot.send_message(chat_id, caption)
