# main.py
import asyncio
import os
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import init_db_pragmas


# === Бот-токен ===
try:
    from config import TOKEN as CONFIG_TOKEN
except Exception:
    CONFIG_TOKEN = None

BOT_TOKEN = os.getenv("BOT_TOKEN") or CONFIG_TOKEN
if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN (ни в .env, ни в config.TOKEN)")

# === Меню (если ещё используешь ReplyKeyboard) ===
try:
    from keyboards import main_menu
except Exception:
    main_menu = None

# === Новые роутеры ===
from handlers import inline_flow, daily_card, admin, clarify_scenarios, clarify_flow
from services.daily import list_due_subscribers
from handlers.daily_card import send_card_of_day
from db.utils import create_all  # функция для создания таблиц

# -------------------------------
# Глобальный «⬅️ В меню»
# -------------------------------
global_router = Router()

@global_router.message(F.text == "⬅️ В меню")
async def return_to_main_menu(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Отмена активных задач (если ещё используешь старые модули)
    try:
        from handlers.custom_question import active_tasks as custom_tasks  # type: ignore
        if user_id in custom_tasks:
            custom_tasks[user_id].cancel()
            del custom_tasks[user_id]
    except Exception:
        pass

    try:
        from handlers.theme_spread import active_tasks as theme_tasks  # type: ignore
        if user_id in theme_tasks:
            theme_tasks[user_id].cancel()
            del theme_tasks[user_id]
    except Exception:
        pass

    await state.clear()

    if main_menu:
        await message.answer("📋 Главное меню:", reply_markup=main_menu)
    else:
        from keyboards_inline import main_menu_inline
        await message.answer("📋 Главное меню:", reply_markup=main_menu_inline())

# -------------------------------
# Планировщик: «Карта дня»
# -------------------------------
scheduler = AsyncIOScheduler(timezone="UTC")

async def send_daily_cards_job(bot: Bot):
    now_utc = datetime.now(timezone.utc)
    due = await list_due_subscribers(now_utc)
    for tg_id, hour, tz in due:
        try:
            await send_card_of_day(bot, tg_id)
        except Exception as e:
            print(f"[Ошибка карты дня] {e}")

# -------------------------------
# Запуск бота
# -------------------------------
async def main():
    # Создаём таблицы (если ещё нет)
    await init_db_pragmas()
    await create_all()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    # Роутеры
    dp.include_router(clarify_scenarios.router)
    dp.include_router(global_router)
    dp.include_router(inline_flow.router)
    dp.include_router(daily_card.router)
    dp.include_router(admin.router)
    dp.include_router(clarify_flow.router)


    # Планировщик
    scheduler.add_job(
        send_daily_cards_job,
        trigger="interval",
        minutes=1,
        args=[bot],
        id="daily_cards_job",
        replace_existing=True,
    )
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exit")
