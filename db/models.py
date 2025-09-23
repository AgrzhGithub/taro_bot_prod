from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, UniqueConstraint, Index, Boolean, Date

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    credits: Mapped[int] = mapped_column(Integer, default=0)  # единый баланс

    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    referred_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    referred_by: Mapped["User"] = relationship(remote_side=[id], uselist=False)

class PromoCode(Base):
    __tablename__ = "promocodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_referral: Mapped[bool] = mapped_column(Boolean, default=False)  # для реф. кода пользователя
    free_credits_award: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    max_uses: Mapped[int | None] = mapped_column(nullable=True)  # None = бесконечно
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("user_id", "promocode_id", name="uq_redemption_user_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    promocode_id: Mapped[int] = mapped_column(ForeignKey("promocodes.id"), index=True)
    redeemed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class Transaction(Base):
    __tablename__ = "transactions"
    # лог оплаты/начислений/списаний
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))  # 'grant' | 'spend'
    amount: Mapped[int] = mapped_column(Integer)   # положительное число
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)  # напр. 'RUB'
    status: Mapped[str] = mapped_column(String(16), default="success")  # 'pending'|'success'|'failed'
    payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class SpreadLog(Base):
    __tablename__ = "spread_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    theme: Mapped[str | None] = mapped_column(String(64), nullable=True)
    spread: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cards: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

# ==== ДОБАВИТЬ В КОНЕЦ db/models.py ====
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, JSON,
    UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from datetime import datetime
# Предполагается, что у тебя уже есть: from .base import Base
# и модель User со столбцами id (PK) и tg_id (int).

class Purchase(Base):
    """
    Факт оплаты (покупки сообщений) через Telegram Payments/ЮKassa.
    Нужен для последующей сверки и ручного дозачисления.
    """
    __tablename__ = "purchases"
    __table_args__ = (
        UniqueConstraint("provider_charge_id", name="uq_purchase_charge_id"),
        Index("ix_purchases_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    tg_id = Column(Integer, nullable=False, index=True)

    credits = Column(Integer, nullable=False)          # куплено сообщений
    amount = Column(Integer, nullable=False)           # сумма в мин. ед. (копейки)
    currency = Column(String(10), nullable=False)      # RUB/ USD и т.д.

    payload = Column(String(255), nullable=False)      # order_{credits}_{amount}
    provider = Column(String(50), default="yookassa")  # провайдер
    provider_charge_id = Column(String(128), nullable=True)

    status = Column(String(32), default="paid")        # paid / credited / failed
    meta = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    credited_at = Column(DateTime, nullable=True)

    user = relationship("User")


class DailySubscription(Base):
    """
    Подписка на ежедневную «Карту дня».
    """
    __tablename__ = "daily_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_daily_sub_user"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    hour = Column(Integer, nullable=False, default=9)         # 0..23 — локальный час
    tz = Column(String(64), nullable=False, default="Europe/Moscow")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

# db/models.py
class SubscriptionPass(Base):
    __tablename__ = "subscription_pass"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    tg_id = Column(Integer, index=True, nullable=False)
    plan = Column(String(32), default="pass_unlim")
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user = relationship("User")

class PassUsage(Base):
    __tablename__ = "pass_usage"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    day = Column(Date, index=True, nullable=False)        # UTC-дата
    used = Column(Integer, default=0, nullable=False)     # сколько раскладов за день
    last_ts = Column(DateTime, default=datetime.utcnow, nullable=False)
