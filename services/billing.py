# services/billing.py
import os
import secrets
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta, date

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db import SessionLocal
from db.models import (
    User, PromoCode, PromoRedemption, Transaction,
    SubscriptionPass, PassUsage
)
from config import (
    DEFAULT_FREE_CREDITS,
    REFERRAL_BONUS_INVITED,
    REFERRAL_BONUS_REFERRER,
    PROMO_DEFAULT_CREDITS,
)


def pluralize_messages(n: int) -> str:
    """
    Возвращает строку с числом и правильным склонением слова «сообщение».
    Пример: 1 сообщение, 2 сообщения, 5 сообщений.
    """
    n = abs(int(n))
    if 11 <= (n % 100) <= 19:
        form = "сообщений"
    else:
        last = n % 10
        if last == 1:
            form = "сообщение"
        elif 2 <= last <= 4:
            form = "сообщения"
        else:
            form = "сообщений"
    return f"{n} {form}"

# =========================
# Общие утилиты / константы
# =========================

def _gen_invite_code(length: int = 6) -> str:
    """
    Генератор инвайт-кода: верхний регистр латиницы + цифры без похожих символов.
    Важно: регистр инвайт-кода намеренно фиксируем, чтобы пользователь видел 'как копировать'.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def get_session() -> AsyncSession:
    return SessionLocal()


# =========================
# Пользователи и баланс
# =========================

async def ensure_user(tg_id: int, username: Optional[str]) -> User:
    """
    Получить/создать пользователя. При первом запуске — создать уникальный invite_code
    и выдать стартовые кредиты DEFAULT_FREE_CREDITS (единый баланс) + ЗАЛОГИРОВАТЬ ЭТО.
    """
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        user = res.scalar_one_or_none()

        if user:
            if username and user.username != username:
                user.username = username
                await session.commit()
            return user

        # Создаём нового
        code = _gen_invite_code()
        while True:
            exists = await session.execute(select(User).where(User.invite_code == code))
            if not exists.scalar_one_or_none():
                break
            code = _gen_invite_code()

        user = User(
            tg_id=tg_id,
            username=username,
            invite_code=code,                   # уже в верхнем регистре
            credits=DEFAULT_FREE_CREDITS,       # единый баланс (включая 2 бесплатных)
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        # 👇 ДОБАВЛЕНО: лог начисления стартовых (2) в transactions
        if (DEFAULT_FREE_CREDITS or 0) > 0:
            session.add(Transaction(
                user_id=user.id,
                type="grant",
                amount=int(DEFAULT_FREE_CREDITS),
                status="success",
                meta={"reason": "welcome_bonus"}
            ))
            await session.commit()

        return user

async def get_user_balance(tg_id: int) -> int:
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        u = res.scalar_one_or_none()
        return 0 if not u else int(u.credits)


async def grant_credits(user_id: int, amount: int, reason: str, meta: Optional[Dict[str, Any]] = None):
    """
    Начислить кредиты пользователю (+ лог транзакции).
    """
    if amount <= 0:
        return
    async with SessionLocal() as session:
        u = await session.get(User, user_id)
        if not u:
            return
        u.credits += amount
        session.add(Transaction(
            user_id=user_id,
            type="grant",
            amount=amount,
            status="success",
            meta=(meta or {}) | {"reason": reason}
        ))
        await session.commit()


async def spend_one_credit(tg_id: int) -> bool:
    """
    Списать 1 кредит у пользователя по tg_id. Возвращает True, если успешно.
    """
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        u: Optional[User] = res.scalar_one_or_none()
        if not u or u.credits <= 0:
            return False
        u.credits -= 1
        session.add(Transaction(
            user_id=u.id,
            type="spend",
            amount=1,
            status="success",
            meta={"reason": "credit_spend"}
        ))
        await session.commit()
        return True


# =========================
# Промокоды и рефералка
# =========================

async def create_referral_promocode_for_user(owner: User) -> PromoCode:
    """
    Реферальный промокод = ТЕКУЩИЙ invite_code владельца (регистрозависимо).
    Если уже существует — возвращаем существующий.
    """
    code_exact = owner.invite_code or ""
    async with SessionLocal() as session:
        res = await session.execute(select(PromoCode).where(PromoCode.code == code_exact))
        p = res.scalar_one_or_none()
        if p:
            return p

        promo = PromoCode(
            code=code_exact,
            is_referral=True,
            free_credits_award=REFERRAL_BONUS_INVITED,
            max_uses=None,   # безлимит по количеству пользователей
            used_count=0,
            created_by_user_id=owner.id,
        )
        session.add(promo)
        await session.commit()
        await session.refresh(promo)
        return promo


async def redeem_promocode(tg_id: int, code: str) -> Tuple[bool, str]:
    """
    Активировать промокод (РЕГИСТРОЗАВИСИМО).
    Логика:
      1) Ищем точное совпадение PromoCode.code == введённая_строка.
      2) Если не найден:
         - проверяем точное совпадение с User.invite_code любого пользователя;
         - если совпало и это НЕ сам пользователь — создаём реферальный промокод на лету и активируем.
      3) Запрещаем самоактивацию (нельзя активировать свой собственный invite_code/реф. код).
      4) Запрещаем повторную активацию одного и того же кода одним пользователем.
      5) Учитываем истечение срока и лимит использований.
      6) Начисляем награду пользователю; если это рефералка — бонус владельцу.
    """
    raw = (code or "").strip()
    if not raw:
        return False, "Введите промокод"

    async with SessionLocal() as session:
        # Кто активирует
        res_user = await session.execute(select(User).where(User.tg_id == tg_id))
        user = res_user.scalar_one_or_none()
        if not user:
            return False, "Пользователь не найден"

        # 1) Точный поиск промокода (case-sensitive)
        res_promo = await session.execute(select(PromoCode).where(PromoCode.code == raw))
        promo = res_promo.scalar_one_or_none()

        # 2) Если промокод не найден — проверим, не точный ли это invite_code владельца
        if not promo:
            res_owner = await session.execute(select(User).where(User.invite_code == raw))
            owner = res_owner.scalar_one_or_none()
            if owner:
                # Нельзя активировать свой же код
                if owner.id == user.id:
                    return False, "Нельзя активировать свой собственный код 😊"
                # Создаём реферальный промокод на лету
                promo = await create_referral_promocode_for_user(owner)
            else:
                return False, "Такого промокода нет"

        # 3) Защита от самоактивации существующего реф. кода
        if promo.is_referral and promo.created_by_user_id == user.id:
            return False, "Нельзя активировать свой собственный код 😊"

        # 4) Запрет повторной активации этого же промокода
        res_red = await session.execute(
            select(PromoRedemption).where(
                and_(
                    PromoRedemption.user_id == user.id,
                    PromoRedemption.promocode_id == promo.id
                )
            )
        )
        if res_red.scalar_one_or_none():
            return False, "Вы уже активировали этот промокод"

        # 5) Срок/лимиты
        now = datetime.utcnow()
        if promo.expires_at and now > promo.expires_at:
            return False, "Срок действия промокода истёк"

        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            return False, "Лимит активаций промокода исчерпан"

        # 6) Начисления пользователю
        award = promo.free_credits_award or PROMO_DEFAULT_CREDITS
        user.credits += award

        # Бонус пригласившему (для рефералок)
        if promo.is_referral and promo.created_by_user_id:
            referrer = await session.get(User, promo.created_by_user_id)
            if referrer:
                referrer.credits += REFERRAL_BONUS_REFERRER
                session.add(Transaction(
                    user_id=referrer.id,
                    type="grant",
                    amount=REFERRAL_BONUS_REFERRER,
                    status="success",
                    meta={"reason": "referral_bonus", "code": promo.code}
                ))

        # Учёт использования промокода + лог транзакции у активирующего
        promo.used_count += 1
        session.add(PromoRedemption(user_id=user.id, promocode_id=promo.id))
        session.add(Transaction(
            user_id=user.id,
            type="grant",
            amount=award,
            status="success",
            meta={"reason": "promo_redeem", "code": promo.code}
        ))

        await session.commit()
        return True, f"Промокод активирован! Начислено {award} сообщений 🎉"


def build_invite_link(invite_code: str) -> str:
    """
    Deep-link для приглашений. При необходимости подставь актуальный @username бота.
    """
    return f"https://t.me/kartataro1_bot?start={invite_code}"


# =========================
# PASS (подписка «псевдобезлимит»)
# =========================

PASS_DAYS = 30
DAY_LIMIT = int(os.getenv("PASS_DAY_LIMIT", 25))         # суточный лимит раскладов по PASS
BURST_PER_MIN = int(os.getenv("PASS_BURST_PER_MIN", 2))  # антиспам: не чаще N в минуту


async def activate_pass_month(user_id: int, tg_id: int, plan: str = "pass_unlim") -> datetime:
    """
    Активировать/продлить PASS на 30 дней (без начисления кредитов).
    """
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
    """
    Вернуть самую свежую запись PASS для пользователя (даже если истекла).
    """
    async with SessionLocal() as s:
        q = (
            select(SubscriptionPass, User)
            .join(User, User.id == SubscriptionPass.user_id)
            .where(User.tg_id == tg_id)
            .order_by(desc(SubscriptionPass.expires_at))
        )
        res = await s.execute(q)
        return res.first()  # (SubscriptionPass, User) | None


async def pass_is_active(tg_id: int) -> bool:
    now = datetime.utcnow()
    row = await _get_latest_active_pass_by_tg(tg_id)
    if not row:
        return False
    sp, _user = row
    return bool(sp.expires_at and sp.expires_at >= now)


async def pass_can_spend(tg_id: int) -> Tuple[bool, str, Optional[int]]:
    """
    Проверка лимитов PASS. Возвращает (ok, why, used_today).
    """
    now = datetime.utcnow()
    today = now.date()

    row = await _get_latest_active_pass_by_tg(tg_id)
    if not row:
        return False, "Подписка не активна", None

    sp, user = row
    if not sp.expires_at or sp.expires_at < now:
        return False, "Срок действия подписки истёк", None

    async with SessionLocal() as s:
        res2 = await s.execute(select(PassUsage).where(PassUsage.user_id == user.id, PassUsage.day == today))
        pu = res2.scalar_one_or_none()

        if pu:
            # антиспам: не чаще BURST_PER_MIN раз в минуту
            min_interval = max(1, 60 / max(1, BURST_PER_MIN))
            if (now - pu.last_ts).total_seconds() < min_interval:
                return False, "Слишком часто. Попробуйте через минуту.", pu.used
            if pu.used >= DAY_LIMIT:
                return False, f"Дневной лимит подписки исчерпан ({DAY_LIMIT}).", pu.used
            return True, "", pu.used

        # ещё не тратили сегодня
        return True, "", 0


async def pass_register_spend(tg_id: int) -> int:
    """
    Зафиксировать расход PASS за сегодня. Возвращает новое значение used.
    """
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
    Сначала пытаемся списать PASS (если активен и лимиты в норме).
    Иначе — списываем 1 кредит. Возвращаем (ok, source_or_reason).
    Возможные ответы:
      - (True,  "pass")            — списано по подписке
      - (True,  "credit")          — списан 1 кредит
      - (False, "pass_rate_limit") — слишком часто (антиспам PASS)
      - (False, "pass_day_limit")  — дневной лимит PASS исчерпан
      - (False, "no_credits")      — нет кредитов (PASS не активен)
      - (False, "pass_inactive")   — PASS активен, но лимиты не позволяют списать
    """
    if await pass_is_active(tg_id):
        ok, why, _ = await pass_can_spend(tg_id)
        if ok:
            await pass_register_spend(tg_id)
            return True, "pass"
        if "Слишком часто" in (why or ""):
            return False, "pass_rate_limit"
        if "Дневной лимит" in (why or ""):
            return False, "pass_day_limit"
        return False, "pass_inactive"

    # PASS не активен — пробуем обычные кредиты
    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        u = res.scalar_one_or_none()
        if not u or u.credits <= 0:
            return False, "no_credits"
        u.credits -= 1
        session.add(Transaction(
            user_id=u.id,
            type="spend",
            amount=1,
            status="success",
            meta={"reason": "credit_spend"}
        ))
        await session.commit()
        return True, "credit"
