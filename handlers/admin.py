# handlers/admin.py
import os
import asyncio
from aiogram import Router, F
from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

import sys, subprocess
from aiogram.types import FSInputFile


from sqlalchemy import select
from db import SessionLocal
from db.models import User

from keyboards_inline import main_menu_inline
from services.billing import grant_credits, get_user_balance
from services.payments import (
    get_recent_uncredited,
    get_purchase_by_charge,
    mark_purchase_credited,
)

router = Router()

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


# ---------------------------
# Покупки / ручное дозачисление
# ---------------------------
@router.message(F.text.startswith("/purchases"))
async def cmd_purchases(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав на эту команду.")
        return
    parts = message.text.strip().split()
    limit = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 10
    rows = await get_recent_uncredited(limit=limit)
    if not rows:
        await message.answer("Нет незачисленных покупок.")
        return
    lines = []
    for p in rows:
        rub = p.amount / 100
        lines.append(
            f"{p.created_at:%d.%m %H:%M} | uid={p.user_id}/tg={p.tg_id} | "
            f"{p.credits} кред | {rub:.2f} {p.currency} | {p.status} | {p.provider_charge_id or '-'}"
        )
    await message.answer("Последние незачисленные покупки:\n" + "\n".join(lines))

@router.message(F.text.startswith("/recredit"))
async def cmd_recredit(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав на эту команду.")
        return
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.answer("Формат: /recredit <provider_charge_id>")
        return
    charge_id = parts[1]
    p = await get_purchase_by_charge(charge_id)
    if not p:
        await message.answer("Покупка не найдена.")
        return
    if p.status == "credited":
        await message.answer("Эта покупка уже зачислена.")
        return

    await grant_credits(
        p.user_id, p.credits,
        reason="admin_recredit",
        meta={"recredit_of": p.id, "charge_id": charge_id}
    )
    await mark_purchase_credited(p.id)
    bal = await get_user_balance(p.tg_id)
    await message.answer(f"✅ Пользователю {p.tg_id} добавлено {p.credits}. Баланс: {bal}")


# ---------------------------
# Админ-рассылка
# ---------------------------
@router.message(F.text.startswith("/push_menu"))
async def push_menu(message: Message):
    """Разослать всем пользователям уведомление + меню.
       Использование:
         /push_menu                    -> дефолтное уведомление
         /push_menu Ваш текст здесь    -> кастомное уведомление
    """
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав на эту команду.")
        return

    # Текст уведомления
    parts = message.text.split(maxsplit=1)
    notice_text = (
        parts[1].strip()
        if len(parts) > 1
        else "🔔 Обновили интерфейс бота: смотрите ниже новое главное меню."
    )

    # Получаем всех пользователей
    async with SessionLocal() as s:
        res = await s.execute(select(User.tg_id))
        ids = [row[0] for row in res.all()]

    await message.answer(f"Начинаю рассылку. Получателей: {len(ids)}")

    sent = 0
    failed = 0

    for uid in ids:
        try:
            # 1) уведомление
            await message.bot.send_message(uid, notice_text)
            # 2) меню
            await message.bot.send_message(uid, "📋 Главное меню:", reply_markup=main_menu_inline())
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)  # мягкий троттлинг

    await message.answer(f"✅ Готово. Отправлено: {sent}, не доставлено: {failed}")


@router.message(F.text.startswith("/push_text"))
async def push_text(message: Message):
    """Разослать произвольный текст всем пользователям.
       Использование: /push_text Текст для всех
    """
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав на эту команду.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /push_text <сообщение>")
        return
    text = parts[1]

    async with SessionLocal() as s:
        res = await s.execute(select(User.tg_id))
        ids = [row[0] for row in res.all()]

    await message.answer(f"Начинаю рассылку текста. Получателей: {len(ids)}")

    sent = 0
    failed = 0
    for uid in ids:
        try:
            await message.bot.send_message(uid, text)
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await message.answer(f"✅ Готово. Отправлено: {sent}, не доставлено: {failed}")

@router.message(F.text.startswith("/backup_now"))
async def backup_now(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав на эту команду.")
        return

    env = os.environ.copy()
    py = sys.executable or "python"

    try:
        proc = subprocess.run([py, "scripts/backup_db.py"], capture_output=True, text=True, env=env, timeout=120)
        if proc.returncode != 0:
            err = (proc.stderr or "Unknown error")[:1500]
            await message.answer(f"❌ Бэкап не удался:\n{err}")
            return

        # ждём строку вида: OK: <путь к zip>
        lines = [l.strip() for l in (proc.stdout or "").splitlines() if l.strip()]
        ok_line = next((l for l in lines if l.startswith("OK:")), None)
        if not ok_line:
            await message.answer("⚠️ Скрипт завершился без OK:. Проверь логи.")
            return

        zip_path = ok_line.split("OK:", 1)[1].strip()
        await message.answer_document(FSInputFile(zip_path), caption="✅ Бэкап готов")
    except Exception as e:
        await message.answer(f"❌ Ошибка бэкапа: {e}")
