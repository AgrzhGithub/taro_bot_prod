import secrets
import os
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta, date

from sqlalchemy import select, and_, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db import SessionLocal
from db.models import User, PromoCode, PromoRedemption, Transaction, SubscriptionPass, PassUsage
from config import (
    DEFAULT_FREE_CREDITS,
    REFERRAL_BONUS_INVITED,
    REFERRAL_BONUS_REFERRER,
    PROMO_DEFAULT_CREDITS,
)

# ---------- Helpers ----------

def _gen_invite_code(length: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих символов
    return "".join(secrets.choice(alphabet) for _ in range(length))

async def get_session() -> AsyncSession:
    return SessionLocal()

# ---------- Users ----------

async def ensure_user(tg_id: int, username: Optional[str]) -> User:
    """Получить или создать пользователя; генерирует invite_code при первом запуске."""
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        user = res.scalar_one_or_none()

        if user:
            if username and user.username != username:
                user.username = username
                await session.commit()
            return user

        # создаём нового
        code = _gen_invite_code()
        while True:
            exists = await session.execute(select(User).where(User.invite_code == code))
            if not exists.scalar_one_or_none():
                break
            code = _gen_invite_code()

        user = User(
            tg_id=tg_id,
            username=username,
            invite_code=code,
            credits=DEFAULT_FREE_CREDITS,   # теперь одно поле
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

async def get_user_balance(tg_id: int) -> int:
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        u = res.scalar_one_or_none()
        if not u:
            return 0
        return u.credits


# ---------- Credits ----------

async def grant_credits(user_id: int, amount: int, reason: str, meta: Optional[Dict[str, Any]] = None):
    """Начислить кредиты + создать транзакцию. meta — опционально для логов."""
    async with SessionLocal() as session:
        u = await session.get(User, user_id)
        if not u:
            return
        u.credits += amount
        meta_final = (meta or {}) | {"reason": reason}
        tx = Transaction(user_id=user_id, type="grant", amount=amount, status="success", meta=meta_final)
        session.add(tx)
        await session.commit()

async def spend_one_credit(tg_id: int) -> bool:
    """Списать 1 кредит. Возвращает True если успешно."""
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        u: Optional[User] = res.scalar_one_or_none()
        if not u or u.credits <= 0:
            return False

        u.credits -= 1
        tx = Transaction(user_id=u.id, type="spend", amount=1, status="success")
        session.add(tx)
        await session.commit()
        return True


# ---------- Promo / Referral ----------

async def create_referral_promocode_for_user(user: User) -> PromoCode:
    """Реферальный промокод = invite_code пользователя."""
    async with SessionLocal() as session:
        res = await session.execute(select(PromoCode).where(PromoCode.code == user.invite_code))
        p = res.scalar_one_or_none()
        if p:
            return p
        promo = PromoCode(
            code=user.invite_code,
            is_referral=True,
            free_credits_award=REFERRAL_BONUS_INVITED,
            max_uses=None,
            used_count=0,
            created_by_user_id=user.id,
        )
        session.add(promo)
        await session.commit()
        await session.refresh(promo)
        return promo

async def redeem_promocode(tg_id: int, code: str) -> tuple[bool, str]:
    """
    Активировать промокод.
    """
    code = code.strip().upper()
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        user = res.scalar_one_or_none()
        if not user:
            return False, "Пользователь не найден"

        res = await session.execute(select(PromoCode).where(PromoCode.code == code))
        promo = res.scalar_one_or_none()

        if not promo:
            return False, "Такого промокода нет"

        if promo.is_referral and promo.created_by_user_id == user.id:
            return False, "Нельзя активировать свой собственный код 😊"

        already = await session.execute(
            select(PromoRedemption).where(
                and_(PromoRedemption.user_id == user.id, PromoRedemption.promocode_id == promo.id)
            )
        )
        if already.scalar_one_or_none():
            return False, "Вы уже активировали этот промокод"

        now = datetime.utcnow()
        if promo.expires_at and now > promo.expires_at:
            return False, "Срок действия промокода истёк"

        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            return False, "Лимит активаций промокода исчерпан"

        # начисляем кредиты
        award = promo.free_credits_award or PROMO_DEFAULT_CREDITS
        user.credits += award

        # бонус пригласившему
        if promo.is_referral and promo.created_by_user_id:
            referrer = await session.get(User, promo.created_by_user_id)
            if referrer:
                referrer.credits += REFERRAL_BONUS_REFERRER
                session.add(Transaction(
                    user_id=referrer.id, type="grant", amount=REFERRAL_BONUS_REFERRER,
                    status="success", meta={"reason": "referral_bonus"}
                ))

        promo.used_count += 1
        session.add(PromoRedemption(user_id=user.id, promocode_id=promo.id))
        session.add(Transaction(
            user_id=user.id, type="grant", amount=award,
            status="success", meta={"reason": "promo_redeem", "code": code}
        ))
        await session.commit()

        return True, f"Промокод активирован! Начислено {award} сообщений 🎉"

def build_invite_link(invite_code: str) -> str:
    return f"https://t.me/kartataro1_bot?start={invite_code}"


# ---------- PASS настройки ----------

PASS_DAYS = 30
# Псевдобезлимит (fair-use)
DAY_LIMIT = int(os.getenv("PASS_DAY_LIMIT", 25))           # сколько раскладов в сутки
BURST_PER_MIN = int(os.getenv("PASS_BURST_PER_MIN", 2))    # не чаще N в минуту


# ---------- PASS: активация/проверка/учёт ----------

async def activate_pass_month(user_id: int, tg_id: int, plan: str = "pass_unlim") -> datetime:
    """Активировать/продлить PASS на 30 дней (без начисления кредитов)."""
    expires = datetime.utcnow() + timedelta(days=PASS_DAYS)
    async with SessionLocal() as s:
        res = await s.execute(select(SubscriptionPass).where(SubscriptionPass.user_id == user_id))
        sp = res.scalar_one_or_none()
        if sp:
            sp.expires_at = expires
            sp.plan = plan
        else:
            s.add(SubscriptionPass(user_id=user_id, tg_id=tg_id, plan=plan, expires_at=expires))
        await s.commit()
    return expires


async def _get_latest_active_pass_by_tg(tg_id: int):
    """Вернуть самую свежую запись PASS для пользователя (даже если истёкшая)."""
    async with SessionLocal() as s:
        q = (
            select(SubscriptionPass, User)
            .join(User, User.id == SubscriptionPass.user_id)
            .where(User.tg_id == tg_id)
            .order_by(desc(SubscriptionPass.expires_at))
        )
        res = await s.execute(q)
        return res.first()  # (SubscriptionPass, User) или None


async def pass_is_active(tg_id: int) -> bool:
    now = datetime.utcnow()
    row = await _get_latest_active_pass_by_tg(tg_id)
    if not row:
        return False
    sp, _user = row
    return sp.expires_at is not None and sp.expires_at >= now


async def pass_can_spend(tg_id: int) -> Tuple[bool, str, Optional[int]]:
    """Проверка лимитов PASS. Возвращает (ok, why, used_today)."""
    now = datetime.utcnow()
    today = now.date()

    row = await _get_latest_active_pass_by_tg(tg_id)
    if not row:
        return False, "PASS не активен", None

    sp, user = row
    if not sp.expires_at or sp.expires_at < now:
        return False, "Срок PASS истёк", None

    async with SessionLocal() as s:
        res2 = await s.execute(select(PassUsage).where(PassUsage.user_id == user.id, PassUsage.day == today))
        pu = res2.scalar_one_or_none()

        if pu:
            # антиспам: не чаще BURST_PER_MIN в минуту
            min_interval = max(1, 60 / max(1, BURST_PER_MIN))
            if (now - pu.last_ts).total_seconds() < min_interval:
                return False, "Слишком часто. Попробуйте через минуту.", pu.used
            if pu.used >= DAY_LIMIT:
                return False, f"Дневной лимит PASS исчерпан ({DAY_LIMIT}).", pu.used
            return True, "", pu.used

        # ещё не тратили сегодня
        return True, "", 0


async def pass_register_spend(tg_id: int) -> int:
    """Зафиксировать расход PASS за сегодня. Возвращает новое значение used."""
    now = datetime.utcnow()
    today = now.date()
    async with SessionLocal() as s:
        res = await s.execute(select(User).where(User.tg_id == tg_id))
        user = res.scalar_one_or_none()
        if not user:
            return 0

        res2 = await s.execute(select(PassUsage).where(PassUsage.user_id == user.id, PassUsage.day == today))
        pu = res2.scalar_one_or_none()
        if pu:
            pu.used += 1
            pu.last_ts = now
            used_now = pu.used
        else:
            pu = PassUsage(user_id=user.id, day=today, used=1, last_ts=now)
            s.add(pu)
            used_now = 1

        await s.commit()
        return used_now


async def spend_one_or_pass(tg_id: int) -> Tuple[bool, str]:
    """
    Пытаемся списать через PASS (если активен и лимиты ОК), иначе списываем 1 кредит.
    Возвращает (ok, source_or_reason), где:
      - ("pass", True) — списали PASS
      - ("credit", True) — списали кредит
      - (False, "pass_rate_limit") — слишком часто (антиспам PASS)
      - (False, "pass_day_limit") — дневной лимит PASS исчерпан
      - (False, "no_credits") — нет кредитов, PASS не активен
      - (False, "pass_inactive") — PASS не активен/истёк и кредитов тоже нет
    """
    if await pass_is_active(tg_id):
        ok, why, _ = await pass_can_spend(tg_id)
        if ok:
            await pass_register_spend(tg_id)
            return True, "pass"
        # Если PASS активен, но упёрся в лимиты — сразу даём конкретную причину,
        # а не молча падаем на кредиты. Так пользователю понятнее.
        if "Слишком часто" in (why or ""):
            return False, "pass_rate_limit"
        if "Дневной лимит" in (why or ""):
            return False, "pass_day_limit"
        return False, "pass_inactive"

    # PASS не активен — пробуем списать обычные кредиты
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        u = res.scalar_one_or_none()
        if not u or u.credits <= 0:
            return False, "no_credits"
        u.credits -= 1
        session.add(Transaction(user_id=u.id, type="spend", amount=1, status="success", meta={"reason": "credit_spend"}))
        await session.commit()
        return True, "credit"
