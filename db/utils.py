# db/utils.py
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import declarative_base

# Если у тебя уже есть эти объекты в db/__init__.py — импортни оттуда:
from db import engine  # async engine
from db.models import Base  # тот же Base, что используют твои модели

async def create_all():
    # Критично: импортируем модели, чтобы они зарегистрировались в Base.metadata
    import db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
