# handlers/daily_card.py
import os
import re
import random
from pathlib import Path
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

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
    rows = []
    for i in range(7, 13, 3):
        row = list(range(i, min(i+3, 13)))
        rows.append(row)
    kb = []
    for row in rows:
        kb.append([
            InlineKeyboardButton(text=f"{h:02d}:01", callback_data=f"daily:time:{h}") for h in row
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
# Фиксированное приветственное медиа (legacy): daily_card.*
# ---------------------------
def _resolve_daily_animation() -> str | None:
    """
    Для приветствия: ИЩЕМ строго data/daily_card.gif|mp4|webm (как раньше).
    Ничего не меняем, чтобы присылалось то же видео.
    """
    exts = (".gif", ".mp4", ".webm")
    # ./data/
    for ext in exts:
        p = os.path.join("data", f"daily_card{ext}")
        if os.path.exists(p):
            return p
    # ../data/ от handlers/
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, ".."))
    for ext in exts:
        p = os.path.join(root, "data", f"daily_card{ext}")
        if os.path.exists(p):
            return p
    return None

async def _send_daily_media_with_caption(bot_or_msg, chat_id: int | None, caption: str) -> bool:
    """
    Для приветствия: отправляем ТО ЖЕ САМОЕ медиа daily_card.* с подписью.
    Больше НЕ досылаем полный текст вторым сообщением (без дублей).
    """
    path = _resolve_daily_animation()
    if not path:
        return False

    ext = os.path.splitext(path)[1].lower()
    f = FSInputFile(path)
    CAP = 1024
    cap = caption if len(caption) <= CAP else (caption[: CAP - 20].rstrip() + "…")

    try:
        # Если у нас Message – используем answer_*, иначе bot.send_*
        if hasattr(bot_or_msg, "answer_video"):
            if ext in (".mp4", ".webm"):
                await bot_or_msg.answer_video(f, caption=cap, supports_streaming=True, request_timeout=180)
            elif ext == ".gif":
                # Гиф как анимация
                await bot_or_msg.answer_animation(f, caption=cap, request_timeout=180)
            else:
                await bot_or_msg.answer_document(f, caption=cap, request_timeout=180)
        else:
            bot = bot_or_msg
            if ext in (".mp4", ".webm"):
                await bot.send_video(chat_id, f, caption=cap, supports_streaming=True, request_timeout=180)
            elif ext == ".gif":
                await bot.send_animation(chat_id, f, caption=cap, request_timeout=180)
            else:
                await bot.send_document(chat_id, f, caption=cap, request_timeout=180)
        return True

    except TelegramNetworkError:
        # Фолбэк: документом
        try:
            if hasattr(bot_or_msg, "answer_document"):
                await bot_or_msg.answer_document(FSInputFile(path), caption=cap, request_timeout=180)
            else:
                bot = bot_or_msg
                await bot.send_document(chat_id, FSInputFile(path), caption=cap, request_timeout=180)
            return True
        except Exception:
            return False
    except TelegramBadRequest:
        # Фолбэк: документом
        try:
            if hasattr(bot_or_msg, "answer_document"):
                await bot_or_msg.answer_document(FSInputFile(path), caption=cap, request_timeout=180)
            else:
                bot = bot_or_msg
                await bot.send_document(chat_id, FSInputFile(path), caption=cap, request_timeout=180)
            return True
        except Exception:
            return False
    except Exception:
        return False

# ---------------------------
# СЛУЧАЙНОЕ ФОТО для «Карты дня» (ТОЛЬКО фото)
# ---------------------------

# Разрешённые ТОЛЬКО фото-расширения
_PHOTO_EXTS = (".jpg", ".jpeg", ".png")

# Папки, где ищем (по приоритету)
_MEDIA_DIRS = [
    Path("data/daily_media"),
    Path("data/daily"),
    Path("data"),
]

_LAST_MEDIA_PATH: str | None = None  # чтобы не повторять тот же файл подряд (в рамках процесса)

def _collect_daily_photo_files() -> list[Path]:
    files: list[Path] = []
    for d in _MEDIA_DIRS:
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() in _PHOTO_EXTS:
                    files.append(p)
    # убрать дубликаты
    uniq = []
    seen = set()
    for p in files:
        k = str(p.resolve())
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq

def _pick_random_daily_photo() -> str | None:
    global _LAST_MEDIA_PATH
    files = _collect_daily_photo_files()
    if not files:
        return None
    if len(files) == 1:
        choice = str(files[0].resolve())
        _LAST_MEDIA_PATH = choice
        return choice
    options = files[:]
    if _LAST_MEDIA_PATH:
        options = [p for p in files if str(p.resolve()) != _LAST_MEDIA_PATH] or files
    choice = str(random.choice(options).resolve())
    _LAST_MEDIA_PATH = choice
    return choice

# ---------------------------
# Отправка «Карты дня»
# ---------------------------
async def send_card_of_day(bot, chat_id: int):
    """
    Отправить «Карту дня» с подписью-толкованием и СЛУЧАЙНЫМ ФОТО
    из data/daily_media|data/daily|data (только jpg/jpeg/png).
    Если фото нет — фолбэк к картинке самой карты (resolve_card_image) или текст.
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

    # Небольшая «чистка» текста и пробел перед «Итог:»
    interpretation_clean = re.sub(r'^\s*\d+[)\.]\s*', '', interpretation, flags=re.MULTILINE)
    interpretation_clean = interpretation_clean.replace("Итог:", "\n\nИтог:")

    caption = f"🗓 Карта дня\n\n🃏 {name}\n\n{interpretation_clean}"

    # 1) пробуем выбрать случайное ФОТО
    media_path = _pick_random_daily_photo()
    if media_path:
        try:
            await bot.send_photo(chat_id, FSInputFile(media_path), caption=caption)
            return
        except Exception:
            pass  # упадём в фолбэк ниже

    # 2) Fallback — если фото нет/не получилось: картинка самой карты
    img_path = resolve_card_image(name)
    if img_path and os.path.exists(img_path):
        await bot.send_photo(chat_id, FSInputFile(img_path), caption=caption)
    else:
        # 3) крайний случай — просто текст
        await bot.send_message(chat_id, caption)

@router.message(Command("test_card"))
async def test_card_cmd(message: Message):
    await send_card_of_day(message.bot, message.chat.id)
