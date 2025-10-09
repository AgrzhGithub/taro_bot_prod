# handlers/daily_card.py
import os
import re
import json
import random
from pathlib import Path
from typing import Iterable

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, FSInputFile, InputFile,
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

# =========================
# Локальные клавиатуры
# =========================
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
    # простая сетка времени: 07:01, 08:01, ..., 12:01
    rows = []
    for i in range(7, 13, 3):
        row = list(range(i, min(i+3, 13)))
        rows.append(row)
    kb = []
    for row in rows:
        kb.append([
            InlineKeyboardButton(text=f"{h:02d}:00", callback_data=f"daily:time:{h}") for h in row
        ])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:daily")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# =========================
# Безопасный edit_text
# =========================
async def _safe_edit(msg, text: str, **kwargs):
    try:
        return await msg.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return msg
        raise

# =========================
# Inline-управление подпиской
# =========================
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

# =========================
# Команды (совместимость)
# =========================
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

# =========================
# Legacy медиа для приветствия (если используешь)
# =========================
def _resolve_daily_animation() -> str | None:
    """
    Для приветствия: ищем строго data/daily_card.gif|mp4|webm (как раньше).
    """
    exts = (".gif", ".mp4", ".webm")
    for ext in exts:
        p = os.path.join("data", f"daily_card{ext}")
        if os.path.exists(p):
            return p
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
    """
    path = _resolve_daily_animation()
    if not path:
        return False

    ext = os.path.splitext(path)[1].lower()
    f = FSInputFile(path)
    CAP = 1024
    cap = caption if len(caption) <= CAP else (caption[: CAP - 20].rstrip() + "…")

    try:
        if hasattr(bot_or_msg, "answer_video"):
            if ext in (".mp4", ".webm"):
                await bot_or_msg.answer_video(f, caption=cap, supports_streaming=True, request_timeout=180)
            elif ext == ".gif":
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

    except (TelegramNetworkError, TelegramBadRequest):
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
    
    # === Рандомное видео для ОБЫЧНЫХ РАСКЛАДОВ (не карта дня) ===
async def _send_spread_media_with_caption(bot_or_msg, caption: str, reply_markup=None) -> bool:
    """
    Отправляет случайное mp4/gif/webm из папки data/spreads/ с подписью.
    Возвращает True, если анимация отправлена; False — если файлов нет/ошибка.
    """
    try:
        import os, random
        from aiogram.types import FSInputFile

        folder = "data/spreads"
        if not os.path.isdir(folder):
            return False

        files = [f for f in os.listdir(folder) if f.lower().endswith((".mp4", ".gif", ".webm"))]
        if not files:
            return False

        path = os.path.join(folder, random.choice(files))
        f = FSInputFile(path)

        # подпись ограничим до ~1024 символов (лимит на caption)
        CAP = 1024
        cap = caption if len(caption) <= CAP else (caption[: CAP - 20].rstrip() + "…")

        # Если это message/callback.message — есть answer_*
        if hasattr(bot_or_msg, "answer_animation"):
            await bot_or_msg.answer_animation(f, caption=cap, reply_markup=reply_markup, request_timeout=180)
            return True
        if hasattr(bot_or_msg, "answer_video"):
            await bot_or_msg.answer_video(f, caption=cap, supports_streaming=True, reply_markup=reply_markup, request_timeout=180)
            return True

        # Иначе считаем, что это bot-объект — нужен chat_id (тут не используем этот путь из inline_flow)
        return False

    except Exception as e:
        print(f"[WARN] _send_spread_media_with_caption failed: {e}")
        return False


# =========================
# Поднабор доступных карт для «Карты дня»
# =========================
_ALLOWED_CARD_NAMES = [
    # --- Старшие арканы (строго по заданному списку, 16 шт.) ---
    "Шут",
    "Маг",
    "Верховная Жрица",
    "Императрица",
    "Император",
    "Иерофант",
    "Влюблённые",
    "Колесница",
    "Сила",
    "Солнце",
    "Отшельник",
    "Колесо Фортуны",
    "Справедливость",
    "Повешенный",
    "Смерть",
    "Умеренность",

    # --- Жезлы ---
    "Туз Жезлы", "3 Жезлы", "10 Жезлы",

    # --- Кубки ---
    "2 Кубки", "3 Кубки", "10 Кубки",


    # --- Мечи ---
    "5 Мечи", "3 Мечи", "Паж Мечи",

    # --- Пентакли ---
    "Рыцарь Пентакли", "Паж Пентакли", "9 Пентакли",
]


# где лежат изображения карт и какие расширения разрешены
_CARD_IMAGE_DIRS: list[Path] = [
    Path("data/cards"),
    Path("data/CARDS"),   # запасной вариант
    Path("data/Карты"),
]
_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# =========================
# Поиск/нормализация имён файлов карт
# =========================
def _norm_filename_base(card_name: str) -> str:
    """
    'Паж Жезлы' -> 'Паж_Жезлы'
    '10 Пентакли' -> '10_Пентакли'
    """
    name = (card_name or "").strip()
    name = re.sub(r"\s+", "_", name)  # пробелы -> _
    name = re.sub(r"[^\wА-Яа-яЁё_0-9]", "", name)  # только буквы/цифры/_
    return name

def _candidate_basenames(card_name: str) -> list[str]:
    """
    Формируем ряд кандидатов, чтобы повысить шанс найти файл.
    """
    exact = _norm_filename_base(card_name)
    cand = [exact]

    # ё -> е
    noyo = exact.replace("ё", "е").replace("Ё", "Е")
    if noyo != exact:
        cand.append(noyo)

    # сжать повторные подчёркивания
    if "__" in exact:
        cand.append(re.sub(r"_+", "_", exact))

    # совсем без подчёркиваний
    if "_" in exact:
        cand.append(exact.replace("_", ""))

    # склонения мастей (на случай чужих файлов)
    repls = {"Мечи": "Мечей", "Кубки": "Кубков", "Жезлы": "Жезлов", "Пентакли": "Пентаклей"}
    for src, dst in repls.items():
        if src in exact:
            cand.append(exact.replace(src, dst))

    # уникализируем, сохраняя порядок
    out, seen = [], set()
    for c in cand:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out

def _iter_existing(paths: Iterable[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None

def find_card_image_path(card_name: str) -> str | None:
    """
    Ищем файл изображения для конкретной карты по каталогам и расширениям.
    1) точные совпадения по кандидатам
    2) мягкий поиск по stem.lower()
    3) fallback: resolve_card_image
    """
    basenames = _candidate_basenames(card_name)

    # (1) прямой перебор
    for base in basenames:
        candidates = []
        for d in _CARD_IMAGE_DIRS:
            for ext in _IMG_EXTS:
                candidates.append((d / f"{base}{ext}").resolve())
        hit = _iter_existing(candidates)
        if hit:
            return str(hit)

    # (2) мягкий перебор
    lowered_targets = [b.lower() for b in basenames]
    for d in _CARD_IMAGE_DIRS:
        if not d.is_dir():
            continue
        try:
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() in _IMG_EXTS:
                    if p.stem.lower() in lowered_targets:
                        return str(p.resolve())
        except Exception:
            continue

    # (3) fallback к вашему резолверу
    try:
        p = resolve_card_image(card_name)
        if p and os.path.exists(p):
            return p
    except Exception:
        pass

    return None

# =========================
# Чтение списка карт и выбор ограниченного поднабора
# =========================
def _load_tarot_list() -> list[dict]:
    for p in (Path("data/tarot_cards.json"), Path("tarot_cards.json")):
        if p.is_file():
            try:
                return json.loads(p.read_text("utf-8"))
            except Exception:
                pass
    return []

def _draw_random_card_limited() -> dict:
    """
    Выбираем карту только из _ALLOWED_CARD_NAMES.
    Если файл JSON не найден/пуст — используем исходную draw_random_card().
    """
    all_cards = _load_tarot_list()
    if not all_cards:
        return draw_random_card()

    allowed_set = set(_ALLOWED_CARD_NAMES)
    filtered = []
    for it in all_cards:
        nm = (it.get("name") or it.get("title") or "").strip()
        if nm in allowed_set:
            filtered.append(it)

    if not filtered:
        return draw_random_card()

    return random.choice(filtered)

# =========================
# Отправка «Карты дня» (ТОЛЬКО фото карты)
# =========================
async def send_card_of_day(bot, chat_id: int):
    """
    Отправить «Карту дня»: изображение ИМЕННО выпавшей карты + толкование.
    Никаких случайных фотографий.
    """
    card = _draw_random_card_limited()
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

    # Небольшая чистка текста и пробел перед «Итог:»
    interpretation_clean = re.sub(r'^\s*\d+[)\.]\s*', '', interpretation, flags=re.MULTILINE)
    interpretation_clean = interpretation_clean.replace("Итог:", "\n\nИтог:")

    caption = f"🗓 Карта дня\n\n🃏 {name}\n\n{interpretation_clean}"

    img_path = find_card_image_path(name)
    if img_path:
        try:
            await bot.send_photo(chat_id, FSInputFile(img_path), caption=caption)
            return
        except Exception:
            pass  # крайний фолбэк ниже

    await bot.send_message(chat_id, caption)

@router.message(Command("test_card"))
async def test_card_cmd(message: Message):
    await send_card_of_day(message.bot, message.chat.id)

# =========================
# Проверки наличия изображений
# =========================
def _find_card_image_any(card_name: str) -> str | None:
    """
    Тот же поиск, что в find_card_image_path, но без fallback к resolve_card_image.
    Удобно для отчётов (видно, каких файлов именно не хватает в data/cards).
    """
    basenames = _candidate_basenames(card_name)
    for base in basenames:
        for d in _CARD_IMAGE_DIRS:
            for ext in _IMG_EXTS:
                p = (d / f"{base}{ext}").resolve()
                if p.is_file():
                    return str(p)
    lowered = [b.lower() for b in basenames]
    for d in _CARD_IMAGE_DIRS:
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in _IMG_EXTS:
                if p.stem.lower() in lowered:
                    return str(p.resolve())
    return None

@router.message(Command("check_cards_images"))
async def check_cards_images_cmd(message: Message):
    """
    Проверяет наличие файлов изображений для ВСЕХ 78 карт (по data/tarot_cards.json).
    """
    tarot_list = _load_tarot_list()
    if not tarot_list:
        await message.answer("❌ Не нашёл список карт: data/tarot_cards.json")
        return

    names = []
    for item in tarot_list:
        n = item.get("name") or item.get("title") or str(item)
        names.append(n.strip())

    missing = []
    found = []
    for name in names:
        hit = _find_card_image_any(name)
        if hit:
            found.append((name, hit))
        else:
            missing.append(name)

    total = len(names)
    have = len(found)
    miss = len(missing)

    text = (
        f"🔎 Проверка изображений (полная колода)\n"
        f"Всего в колоде: **{total}**\n"
        f"Найдено файлов: **{have}**\n"
        f"Отсутствует: **{miss}**\n"
    )
    if miss == 0:
        await message.answer(text + "\n✅ Все изображения на месте!")
        return

    report_path = Path("missing_cards.txt")
    report_path.write_text("\n".join(missing), encoding="utf-8")

    await message.answer(text + "\n⚠️ Прикладываю список отсутствующих.")
    try:
        await message.answer_document(InputFile(str(report_path)))
    except Exception:
        await message.answer("Отсутствуют:\n" + "\n".join(missing[:50]) + ("\n…" if miss > 50 else ""))

@router.message(Command("check_cards_images_lite"))
async def check_cards_images_lite_cmd(message: Message):
    """
    Проверяет наличие файлов изображений ТОЛЬКО для поднабора _ALLOWED_CARD_NAMES.
    """
    missing = []
    found = []
    for name in _ALLOWED_CARD_NAMES:
        hit = _find_card_image_any(name)
        if hit:
            found.append((name, hit))
        else:
            missing.append(name)

    total = len(_ALLOWED_CARD_NAMES)
    have = len(found)
    miss = len(missing)

    text = (
        f"🔎 Проверка изображений (поднабор для Карты дня)\n"
        f"В поднаборе: **{total}**\n"
        f"Найдено файлов: **{have}**\n"
        f"Отсутствует: **{miss}**\n"
    )
    if miss == 0:
        await message.answer(text + "\n✅ Все изображения на месте!")
        return

    report_path = Path("missing_cards_lite.txt")
    report_path.write_text("\n".join(missing), encoding="utf-8")

    await message.answer(text + "\n⚠️ Прикладываю список отсутствующих (поднабор).")
    try:
        await message.answer_document(InputFile(str(report_path)))
    except Exception:
        await message.answer("Отсутствуют:\n" + "\n".join(missing[:50]) + ("\n…" if miss > 50 else ""))
