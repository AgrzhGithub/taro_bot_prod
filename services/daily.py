# services/daily.py
import os
import json
import random
from datetime import datetime
from typing import Optional, List, Tuple
import pytz
from sqlalchemy import select, delete, update

from db import SessionLocal
from db.models import User, DailySubscription  # DailySubscription добавили в models.py

# пути к файлам
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CARDS_JSON = os.path.join(BASE_DIR, "data", "tarot_cards.json")
CARDS_DIR = os.getenv("CARDS_DIR", os.path.join(BASE_DIR, "assets", "cards"))
CARDS_MAP_PATH = os.path.join(CARDS_DIR, "cards_map.json")

# ----------- Загрузка списка карт и выбор случайной карты -----------
def load_cards() -> List[dict]:
    """Читает список карт из data/tarot_cards.json"""
    if not os.path.exists(CARDS_JSON):
        raise FileNotFoundError(f"Нет файла {CARDS_JSON}")
    with open(CARDS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def draw_random_card() -> dict:
    """Возвращает одну случайную карту (dict) из tarot_cards.json"""
    cards = load_cards()
    return random.choice(cards)

# ----------- Картинка для карты -----------
def resolve_card_image(card_name: str) -> Optional[str]:
    """
    1) ищем точное совпадение в cards_map.json (русское → имя файла),
    2) иначе: мягкий поиск по подстроке (латиница/подчёркивания).
    """
    if not card_name:
        return None

    try:
        if os.path.exists(CARDS_MAP_PATH):
            with open(CARDS_MAP_PATH, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            fname = mapping.get(card_name)
            if fname:
                path = os.path.join(CARDS_DIR, fname)
                if os.path.exists(path):
                    return path
    except Exception:
        pass

    safe = (
        card_name.replace(" ", "_")
                 .replace("-", "_")
                 .replace("ё", "е")
    ).lower()

    if os.path.isdir(CARDS_DIR):
        for fname in os.listdir(CARDS_DIR):
            low = fname.lower()
            if safe in low and low.endswith((".jpg", ".jpeg", ".png")):
                return os.path.join(CARDS_DIR, fname)

    return None

# ----------- Подписки на «Карту дня» -----------
async def subscribe_daily(user_tg_id: int, hour: int = 9, tz: str = "Europe/Moscow"):
    try:
        hour = int(hour)
    except Exception:
        hour = 9
    hour = max(0, min(23, hour))

    async with SessionLocal() as s:
        res = await s.execute(select(User).where(User.tg_id == user_tg_id))
        u = res.scalar_one_or_none()
        if not u:
            return False, "Сначала запустите бота командой /start"

        res = await s.execute(select(DailySubscription).where(DailySubscription.user_id == u.id))
        sub = res.scalar_one_or_none()
        if sub:
            await s.execute(
                update(DailySubscription)
                .where(DailySubscription.id == sub.id)
                .values(hour=hour, tz=tz)
            )
        else:
            s.add(DailySubscription(user_id=u.id, hour=hour, tz=tz))
        await s.commit()

    return True, f"Подписка оформлена: каждый день в {hour:02d}:00 ({tz})."

async def unsubscribe_daily(user_tg_id: int):
    async with SessionLocal() as s:
        res = await s.execute(select(User).where(User.tg_id == user_tg_id))
        u = res.scalar_one_or_none()
        if not u:
            return False, "Пользователь не найден"
        await s.execute(delete(DailySubscription).where(DailySubscription.user_id == u.id))
        await s.commit()

    return True, "Ежедневная рассылка отключена."

async def list_due_subscribers(now_utc: datetime) -> List[Tuple[int, int, str]]:
    """
    Вернуть (tg_id, hour, tz) пользователей, у кого сейчас наступил их локальный час (мин == 0).
    """
    out: List[Tuple[int, int, str]] = []
    async with SessionLocal() as s:
        res = await s.execute(
            select(DailySubscription, User).join(User, DailySubscription.user_id == User.id)
        )
        rows = res.all()
        for sub, user in rows:
            try:
                tz = pytz.timezone(sub.tz or "Europe/Moscow")
            except Exception:
                tz = pytz.timezone("Europe/Moscow")
            local_now = now_utc.astimezone(tz)
            if local_now.minute == 0 and local_now.hour == sub.hour:
                out.append((user.tg_id, sub.hour, sub.tz))
    return out
