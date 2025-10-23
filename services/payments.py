# services/payments.py
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, update
from db import SessionLocal
from db.models import Purchase

async def create_purchase(*, tg_id: int, user_id: int, credits: int, amount: int,
                          currency: str, payload: str, provider: str,
                          provider_charge_id: Optional[str], meta: Optional[dict]) -> int:
    async with SessionLocal() as s:
        p = Purchase(
            user_id=user_id, tg_id=tg_id, credits=credits,
            amount=amount, currency=currency, payload=payload,
            provider=provider, provider_charge_id=provider_charge_id,
            status="pending", meta=meta or {}
        )
        s.add(p)
        await s.commit()
        return p.id

async def mark_purchase_credited(purchase_id: int):
    async with SessionLocal() as s:
        await s.execute(
            update(Purchase)
            .where(Purchase.id == purchase_id)
            .values(status="credited", credited_at=datetime.utcnow())
        )
        await s.commit()

async def get_purchase_by_charge(charge_id: str) -> Optional[Purchase]:
    async with SessionLocal() as s:
        res = await s.execute(select(Purchase).where(Purchase.provider_charge_id == charge_id))
        return res.scalar_one_or_none()

async def get_recent_uncredited(limit: int = 20) -> List[Purchase]:
    async with SessionLocal() as s:
        res = await s.execute(
            select(Purchase)
            .where(Purchase.status != "credited")
            .order_by(Purchase.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars().all())
