# db/__init__.py
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from config import DATABASE_URL

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
    class_=AsyncSession,
)

async def init_db_pragmas() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.execute(text("PRAGMA synchronous=NORMAL;"))
