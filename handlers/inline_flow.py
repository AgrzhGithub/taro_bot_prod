# handlers/inline_flow.py
from __future__ import annotations

from services import tarot_ai
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardRemove, PreCheckoutQuery, LabeledPrice,
    InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
import os
from datetime import datetime, date

from sqlalchemy import select

from keyboards_inline import (
    main_menu_inline, theme_inline, spread_inline, buy_inline, back_to_menu_inline,
    promo_inline, advice_inline_limits, advice_pack_buy_inline,
)
from config import ADMIN_USERNAME
from services.tarot_ai import draw_cards, gpt_make_prediction, merge_with_scenario, gpt_make_advice_from_yandex_answer
from services.billing import (
    ensure_user, get_user_balance, redeem_promocode,
    build_invite_link, grant_credits, activate_pass_month,
    spend_one_or_pass,           # использовать для списаний только при раскладах/вопросах
    pass_is_active,
    spend_one_advice,            # списываем 1 совет из пакета
    get_advice_balance_by_tg_id, # остаток советов по tg_id
    pluralize_advices,
)
from handlers.daily_card import _send_daily_media_with_caption, _send_spread_media_with_caption
from services.payments import create_purchase, mark_purchase_credited
from db import SessionLocal, models

router = Router()


# ---------- FSM ----------
class PromoFSM(StatesGroup):
    waiting_code = State()


class CustomFSM(StatesGroup):
    waiting_question = State()


# ---------- Утилиты ----------
def _card_names(cards) -> list[str]:
    names = []
    for c in cards:
        if isinstance(c, str):
            names.append(c)
        elif isinstance(c, dict):
            names.append(c.get("name") or c.get("title") or c.get("ru") or c.get("en") or str(c))
        else:
            names.append(str(c))
    return names


def _format_date_human(val) -> str:
    """Безопасное форматирование даты в DD.MM.YYYY для datetime/date/ISO-строки."""
    if isinstance(val, (datetime, date)):
        return val.strftime("%d.%m.%Y")
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val).strftime("%d.%m.%Y")
        except Exception:
            return val
    return str(val)


async def _get_pass_expiry_by_tg(tg_id: int):
    """Возвращает expires_at для PASS по tg_id (или None). Ничего не списывает."""
    async with SessionLocal() as s:
        q = (
            select(models.SubscriptionPass.expires_at)
            .join(models.User, models.User.id == models.SubscriptionPass.user_id)
            .where(models.User.tg_id == tg_id)
            .order_by(models.SubscriptionPass.expires_at.desc())
        )
        res = await s.execute(q)
        return res.scalar_one_or_none()


def _extract_itog(text: str) -> str:
    """
    Возвращает текст раздела 'Итог' из сгенерированного ответа.
    Если 'Итог' не найден, возвращает пустую строку.
    """
    if not text:
        return ""
    lines = text.splitlines()
    itog_idx = next((i for i, line in enumerate(lines) if line.strip().lower().startswith("итог")), None)
    if itog_idx is None:
        itog_idx = next((i for i, line in enumerate(lines) if "итог" in line.strip().lower()), None)
    if itog_idx is None:
        return ""
    tail = [s for s in lines[itog_idx+1:] if s.strip()]
    return " ".join(tail).strip()


def _get_message_text(msg: Message) -> str:
    """Возвращает текст сообщения: text или caption."""
    return (msg.text or msg.caption or "").strip()


async def _edit_text_or_caption(msg: Message, text: str, reply_markup=None) -> bool:
    """
    Аккуратно редактирует текст или подпись в зависимости от типа сообщения.
    Возвращает True, если удалось отредактировать, иначе отправляет новое сообщение и возвращает False.
    """
    try:
        # Если у сообщения есть медиа (photo/video/animation/document) — редактируем подпись
        if getattr(msg, "photo", None) or getattr(msg, "video", None) or getattr(msg, "animation", None) or getattr(msg, "document", None):
            await msg.edit_caption(text, reply_markup=reply_markup)
        else:
            await msg.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest:
        # Если редактирование невозможно (например, слишком старое сообщение) — отправим новое.
        await msg.answer(text, reply_markup=reply_markup)
        return False


# ---------- Клавиатуры ----------
def _advice_back_kb(allow_three: bool = True) -> InlineKeyboardMarkup:
    """
    Клавиатура под советом: вернуться к предсказанию (+ опционально расширенный совет).
    """
    rows = [[InlineKeyboardButton(text="⬅️ К предсказанию", callback_data="advice:back")]]
    if allow_three:
        rows.append([InlineKeyboardButton(text="🔮 Расширенный совет (3 карты)", callback_data="advice:3")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- старт/меню/хелп ----------
@router.message(CommandStart())
async def start_inline(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username)
    welcome1 = (
        "🔮 Добро пожаловать в волшебный мир Таро!\n\n"
        "Перед вами не просто бот, а Ваш главный проводник в мир Таро. "
        "Помощник, обученный на лучших книгах о предсказаниях по картам Таро.\n\n"
        "✨ Как работает магия:\n"
        "Прежде чем задать вопрос, позвольте себе несколько мгновений покоя. Сделайте глубокий вдох, "
        "отпустите тревоги и сосредоточьтесь на своей интуиции. Чем спокойнее будет ваш разум, тем яснее заговорят карты.\n"
        "1) Выберите интересующую вас тему: любовь, отношения, будущее, работа или иной жизненный вопрос.\n"
        "2) Я раскрою перед вами карты — от простых трёхкартных раскладов до древних схем вроде «Подковы» или «Алхимика».\n"
        "3) В конце каждого расклада вы получите «Итог» — суть послания карт. "
        "А для тех, кто хочет большего, есть \n"
        "✨Советы: одна или три карты, которые укажут направление действий.\n\n"
    )

    welcome2 = (
        "🌙 Бесплатные возможности:\n"
        "— «🗓 Карта дня» — каждый день вы можете получать особую карту, "
        "которая задаёт тон и настроение вашему пути. "
        "С ней можно прожить день осознанно и увидеть скрытые подсказки судьбы.\n\n"
        "💎 Дополнительно:\n"
        "— У вас есть возможность активировать промокод и получить бесплатный расклад.\n"
        "— Вы можете приобрести доступ к советам или оформить подписку, открывающую "
        "все магические функции.\n\n"
        "⚡️ В любой момент вы можете вернуться в главное меню и начать новый путь. "
        "Карты уже ждут вас — задайте вопрос, и они ответят так, как не ответит никто другой…\n\n"
        "🔮 Пусть Вас ждет как можно больше положительных новостей и эмоций! 😊"
    )

    sent = await _send_daily_media_with_caption(message, None, welcome1)
    if not sent:
        await message.answer(welcome1)
    await message.answer(welcome2)
    await message.answer("📋 Главное меню:", reply_markup=main_menu_inline())


@router.message(Command("menu"))
async def menu_cmd(message: Message):
    await message.answer("📋 Главное меню:", reply_markup=main_menu_inline())


@router.callback_query(F.data == "menu:help")
async def help_screen(cb: CallbackQuery):
    await cb.answer()
    txt = (
        "❓ Помощь\n\n"
        "• 1 расклад = 1 сообщение.\n"
        "• «🗓 Карта дня» — бесплатно (включите /card_daily_on).\n"
        "• Покупки: «🛒 Купить» (пакеты сообщений или подписка).\n"
        "• Конфиденциальность: ваши сообщения не передаются третьим лицам.\n"
        "• Не является мед/юр консультацией.\n"
    )
    if cb.message.text != txt:
        await _edit_text_or_caption(cb.message, txt, reply_markup=main_menu_inline())
    else:
        await cb.message.edit_reply_markup(reply_markup=main_menu_inline())


@router.callback_query(F.data == "nav:menu")
async def nav_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await _edit_text_or_caption(cb.message, "📋 Главное меню:", reply_markup=main_menu_inline())


# ---------- темы/расклады ----------
@router.callback_query(F.data == "menu:theme")
async def menu_theme(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await _edit_text_or_caption(cb.message, "Выберите тему:", reply_markup=theme_inline())


@router.callback_query(F.data.startswith("theme:"))
async def pick_theme(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    theme = cb.data.split(":", 1)[1]
    await state.update_data(theme=theme)
    await _edit_text_or_caption(cb.message, f"Тема: {theme}\nВыберите расклад:", reply_markup=spread_inline())


@router.callback_query(F.data == "nav:theme")
async def back_to_theme(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await _edit_text_or_caption(cb.message, "Выберите тему:", reply_markup=theme_inline())


@router.callback_query(F.data.startswith("spread:"))
async def pick_spread(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    spread = cb.data.split(":", 1)[1]
    data = await state.get_data()

    theme = data.get("theme", "Общая")
    scenario_ctx = data.get("scenario_ctx")
    user_question = (
        data.get("user_question")
        or data.get("question")
        or data.get("last_question")
        or ""
    )

    ok, src = await spend_one_or_pass(cb.from_user.id)
    if not ok:
        if src == "pass_rate_limit":
            await _edit_text_or_caption(cb.message, "⏳ Слишком часто. Попробуйте через минуту.", reply_markup=main_menu_inline())
        elif src == "pass_day_limit":
            await _edit_text_or_caption(cb.message, "📅 Дневной лимит подписки исчерпан. Попробуйте завтра.", reply_markup=main_menu_inline())
        else:
            await _edit_text_or_caption(cb.message, "❌ Нет доступных сообщений. Купите пакет или оформите подписку 🛒", reply_markup=main_menu_inline())
        await state.clear()
        return

    if spread == "Три карты":
        cards = draw_cards(3)
    elif spread == "Подкова":
        cards = draw_cards(7)
    elif spread == "Алхимик":
        cards = draw_cards(4)
    else:
        cards = draw_cards(3)

    names = _card_names(cards)
    cards_list = ", ".join(names)
    await _edit_text_or_caption(cb.message, f"🎴 Расклад: {spread}\n🃏 Карты: {cards_list}\n\n🔮 Делаю толкование...")

    try:
        prediction = await gpt_make_prediction(
            question=user_question,
            theme=theme,
            spread=spread,
            cards_list=cards_list,
            scenario_ctx=scenario_ctx,
        )
    except Exception as e:
        prediction = f"⚠️ Не удалось получить толкование: {e}"

    user = await ensure_user(cb.from_user.id, cb.from_user.username)
    async with SessionLocal() as s:
        s.add(models.SpreadLog(user_id=user.id, theme=theme, spread=spread, cards={"cards": names}, cost=1))
        await s.commit()

    itog = _extract_itog(prediction)
    await state.update_data(
        last_theme=theme,
        last_spread=spread,
        last_question=user_question,
        last_cards=names,
        last_itog=itog,
        last_scenario=scenario_ctx,
        last_prediction_text=prediction,
    )

    kb = advice_inline_limits(True, True)
    sent = await _send_spread_media_with_caption(cb.message, prediction, reply_markup=kb)
    if not sent:
        await _edit_text_or_caption(cb.message, prediction, reply_markup=kb)


# ---------- СОВЕТЫ ----------
@router.callback_query(F.data.in_({"advice:1", "advice:3", "ownq:advice:1", "ownq:advice:3"}))
async def advice_handler(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    is_one = cb.data.endswith(":1")
    advice_count = 1 if is_one else 3

    has_pass = await pass_is_active(cb.from_user.id)

    # --- Расширенный совет (3) — только по подписке ---
    if advice_count == 3:
        if not has_pass:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оформить подписку — 299₽", callback_data="buy:pass30:29900")],
                [InlineKeyboardButton(text="⬅️ К предсказанию", callback_data="advice:back")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ])
            await _edit_text_or_caption(
                cb.message,
                "🔒 Расширенный совет (3 карты) доступен по подписке.\n"
                "Оформите 30-дневный доступ — и сможете пользоваться и обычным, и расширенным советом.",
                reply_markup=kb
            )
            return

        # подписка активна → генерируем на 3
        data = await state.get_data()
        base_answer = (_get_message_text(cb.message) or data.get("last_prediction_text") or "").strip()
        try:
            cards = draw_cards(3)
            card_names = [c["name"] for c in cards]
        except Exception:
            card_names = []
        try:
            advice_text = await gpt_make_advice_from_yandex_answer(
                yandex_answer_text=base_answer,
                advice_cards_list=card_names,
                advice_count=3,
            )
        except Exception as e:
            advice_text = f"⚠️ Не удалось получить совет: {e}"

        await _edit_text_or_caption(cb.message, advice_text, reply_markup=_advice_back_kb(allow_three=False))
        return

    # --- Обычный совет (1) ---
    pkg_spent = await spend_one_advice(cb.from_user.id)
    if not pkg_spent:
        if has_pass:
            pass
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Пакет советов (3) — 80₽", callback_data="buy:advicepack3:8000")],
                [InlineKeyboardButton(text="⬅️ К предсказанию", callback_data="advice:back")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ])
            await _edit_text_or_caption(cb.message, "У вас нет доступных советов.\nВыберите вариант получения:", reply_markup=kb)
            return

    data = await state.get_data()
    base_answer = (_get_message_text(cb.message) or data.get("last_prediction_text") or "").strip()

    try:
        cards = draw_cards(1)
        card_names = [c["name"] for c in cards]
    except Exception:
        card_names = []

    try:
        advice_text = await gpt_make_advice_from_yandex_answer(
            yandex_answer_text=base_answer,
            advice_cards_list=card_names,
            advice_count=1,
        )
    except Exception as e:
        advice_text = f"⚠️ Не удалось получить совет: {e}"

    await _edit_text_or_caption(cb.message, advice_text, reply_markup=_advice_back_kb(allow_three=True))


@router.callback_query(F.data == "advice:back")
async def advice_back_to_prediction(cb: CallbackQuery, state: FSMContext):
    """Возврат к последнему предсказанию с кнопками советов."""
    await cb.answer()
    data = await state.get_data()
    prediction = (data.get("last_prediction_text") or "").strip()
    if not prediction:
        await _edit_text_or_caption(cb.message, "Предсказание недоступно. Попробуйте сделать расклад заново.", reply_markup=main_menu_inline())
        return
    await _edit_text_or_caption(cb.message, prediction, reply_markup=advice_inline_limits(allow_one=True, allow_three=True))


# ---------- свой вопрос ----------
@router.callback_query(F.data == "menu:custom")
async def custom_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(CustomFSM.waiting_question)
    hint = (
        "Напишите свой вопрос одним сообщением ⬇️\n\n"
        "Примеры:\n"
        "• Что поможет в работе на этой неделе?\n"
        "• Как наладить отношения с близким человеком?\n"
        "• На что обратиться внимание в самочувствии?\n"
    )
    await _edit_text_or_caption(cb.message, hint, reply_markup=back_to_menu_inline())


@router.message(CustomFSM.waiting_question, F.text)
async def custom_receive(message: Message, state: FSMContext):
    question = message.text.strip()

    ok, src = await spend_one_or_pass(message.from_user.id)
    if not ok:
        if src == "pass_rate_limit":
            await message.answer("⏳ Слишком часто. Попробуйте через минуту.", reply_markup=main_menu_inline())
        elif src == "pass_day_limit":
            await message.answer("📅 Дневной лимит подписки исчерпан. Попробуйте завтра.", reply_markup=main_menu_inline())
        else:
            await message.answer("❌ Нет доступных сообщений. Купите пакет или оформите подписку 🛒", reply_markup=main_menu_inline())
        await state.clear()
        return

    cards = draw_cards(3)
    names = _card_names(cards)
    cards_list = ", ".join(names)
    await message.answer(f"🃏 Карты: {cards_list}\n\n🔮 Делаю толкование...")

    try:
        prediction = await gpt_make_prediction(
            question=question,
            theme="Пользовательский вопрос",
            spread="custom",
            cards_list=cards_list
        )
    except Exception:
        prediction = "⚠️ Не удалось получить толкование. Попробуйте ещё раз."

    user = await ensure_user(message.from_user.id, message.from_user.username)
    async with SessionLocal() as s:
        s.add(models.SpreadLog(user_id=user.id, question=question, spread="custom", cards={"cards": names}, cost=1))
        await s.commit()

    await state.update_data(
        user_question=question,
        last_question=question,
        last_cards=names,
        last_spread="custom",
        last_theme="Пользовательский вопрос",
        last_itog=_extract_itog(prediction),
        last_prediction_text=prediction,
    )

    kb = advice_inline_limits(allow_one=True, allow_three=True)
    sent = await _send_spread_media_with_caption(message, prediction, reply_markup=kb)
    if not sent:
        await message.answer(prediction, reply_markup=kb)


# ---------- промокод ----------
@router.callback_query(F.data == "menu:promo")
async def promo_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(PromoFSM.waiting_code)
    await _edit_text_or_caption(cb.message, "Введите промокод сообщением ⬇️", reply_markup=back_to_menu_inline())


@router.message(PromoFSM.waiting_code, F.text)
async def promo_redeem(message: Message, state: FSMContext):
    code = message.text.strip()
    ok, msg = await redeem_promocode(message.from_user.id, code)
    await message.answer(msg, reply_markup=main_menu_inline())
    await state.clear()


# ---------- профиль ----------
@router.callback_query(F.data == "menu:profile")
async def show_profile(cb: CallbackQuery):
    await cb.answer()
    user = await ensure_user(cb.from_user.id, cb.from_user.username)

    balance_msgs = await get_user_balance(cb.from_user.id)
    advice_left = await get_advice_balance_by_tg_id(cb.from_user.id)

    is_active = await pass_is_active(cb.from_user.id)
    pass_line = "🎫 Подписка не активна"
    if is_active:
        expires = await _get_pass_expiry_by_tg(cb.from_user.id)
        if expires:
            pass_line = f"🎫 Подписка активна до {_format_date_human(expires)}"

    link = build_invite_link(user.invite_code)

    txt = (
        "👤 Ваш профиль\n\n"
        f"💬 Доступных сообщений: {balance_msgs}\n"
        f"💡 Доступных советов: {advice_left}\n"
        f"{pass_line}\n\n"
        f"🔗 Ваш реферальный код: {user.invite_code}\n"
        f"▶️ Ссылка для приглашений:\n{link}"
    )

    await _edit_text_or_caption(cb.message, txt, reply_markup=promo_inline())


# ---------- покупка (кредиты + PASS + советы) ----------
PROVIDER_TOKEN = os.getenv("PAYMENTS_PROVIDER_TOKEN")
CURRENCY = os.getenv("CURRENCY", "RUB")
ADVICE_ONE_PRICE_KOPECKS = int(os.getenv("ADVICE_ONE_PRICE_KOPECKS", "8000"))  # 80₽ по умолчанию

@router.callback_query(F.data == "menu:buy")
async def buy_menu(cb: CallbackQuery):
    await cb.answer()
    await _edit_text_or_caption(cb.message, "Выберите пакет:", reply_markup=buy_inline())


@router.callback_query(F.data.startswith("buy:"))
async def buy_pick(cb: CallbackQuery, bot: Bot):
    await cb.answer()
    if not PROVIDER_TOKEN:
        await _edit_text_or_caption(cb.message, "⚠️ Платёжный провайдер не настроен. Добавьте PAYMENTS_PROVIDER_TOKEN в .env", reply_markup=main_menu_inline())
        return

    parts = cb.data.split(":")
    kind = parts[1]  # "credits" | "pass30" | "advice1" | "advicepack3"

    if kind == "credits":
        credits = int(parts[2])
        amount = int(parts[3])
        title = f"{credits} сообщений — {amount // 100}₽"
        payload = f"credits_{credits}_{amount}"
        description = f"Пакет на {credits} сообщений"
    elif kind == "pass30":
        amount = int(parts[2])
        title = f"Подписка (30 дней) — {amount // 100}₽"
        payload = f"pass30_{amount}"
        description = "Безлимитный месячный доступ"
    elif kind == "advicepack3":
        amount = int(parts[2])
        title = f"Пакет советов (3) — {amount // 100}₽"
        payload = f"advicepack3_{amount}"
        description = "Пакет из 3 советов (используется по кнопке «Совет»)"
    elif kind == "advice1":
        amount = int(parts[2])
        title = f"Разовый совет — {amount // 100}₽"
        payload = f"advice1_{amount}"
        description = "Оплата разового совета к текущему раскладу"
    else:
        await cb.message.answer("Неизвестный тип покупки.", reply_markup=main_menu_inline())
        return

    await bot.send_invoice(
        chat_id=cb.message.chat.id,
        title=title,
        description=description,
        payload=payload,
        provider_token=PROVIDER_TOKEN,
        currency=CURRENCY,
        prices=[LabeledPrice(label=title, amount=amount)],
    )


@router.pre_checkout_query()
async def pre_checkout(pre: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre.id, ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext):
    sp = message.successful_payment
    payload = sp.invoice_payload or ""
    currency = (sp.currency or CURRENCY).strip()
    total_amount = int(sp.total_amount or 0)

    charge_id = getattr(sp, "provider_payment_charge_id", None) or getattr(sp, "telegram_payment_charge_id", None)

    user = await ensure_user(message.from_user.id, message.from_user.username)

    purchase_id = await create_purchase(
        tg_id=message.from_user.id,
        user_id=user.id,
        credits=0,
        amount=total_amount,
        currency=currency,
        payload=payload,
        provider="yookassa",
        provider_charge_id=charge_id,
        meta={"raw": sp.model_dump()},
    )

    # 1) Разовый платёж за обычный совет
    if payload.startswith("advice1_"):
        await mark_purchase_credited(purchase_id)

        data = await state.get_data()
        yandex_answer = (data.get("last_prediction_text") or "").strip()

        try:
            advice_cards = draw_cards(1)
            advice_card_names = [c["name"] for c in advice_cards]
        except Exception:
            advice_card_names = []

        try:
            advice_text = await gpt_make_advice_from_yandex_answer(
                yandex_answer_text=yandex_answer,
                advice_cards_list=advice_card_names,
                advice_count=1,
            )
        except Exception as e:
            advice_text = f"⚠️ Не удалось получить совет: {e}"

        note = f"\nID платежа: {charge_id}" if charge_id else ""
        await message.answer(
            advice_text + note,
            reply_markup=_advice_back_kb(allow_three=True)
        )
        return

    # 2) Пакет советов (3 шт.)
    if payload.startswith("advicepack3_"):
        await mark_purchase_credited(purchase_id)
        try:
            from services.billing import grant_advice_pack, get_advice_balance_by_tg_id
            await grant_advice_pack(user.id, qty=3, reason="advice_pack_3_purchase")
            try:
                from services.billing import pluralize_advices
                bal_adv = await get_advice_balance_by_tg_id(message.from_user.id)
                adv_note = f"\n🧠 Доступно: {pluralize_advices(bal_adv)}"
            except Exception:
                adv_note = ""
        except Exception:
            adv_note = ""

        note = f"\nID платежа: {charge_id}" if charge_id else ""
        await message.answer(
            f"✅ Пакет советов (3) активирован.{adv_note}{note}",
            reply_markup=main_menu_inline()
        )
        return

    # 3) Пакеты сообщений
    if payload.startswith("credits_"):
        parts = payload.split("_")
        credits = int(parts[1])

        await grant_credits(user.id, credits, reason=f"payment_{total_amount}")
        await mark_purchase_credited(purchase_id)

        bal = await get_user_balance(message.from_user.id)
        note = f"\nID платежа: {charge_id}" if charge_id else ""
        await message.answer(
            f"✅ Пакет на {credits} сообщений активирован.\n"
            f"Баланс: {bal}.{note}",
            reply_markup=main_menu_inline()
        )
        return

    # 4) Подписка PASS
    if payload.startswith("pass30_"):
        expires = await activate_pass_month(user.id, message.from_user.id, plan="pass_unlim")
        await mark_purchase_credited(purchase_id)

        note = f"\nID платежа: {charge_id}" if charge_id else ""
        await message.answer(
            "✅ Подписка на 30 дней активирована.\n"
            f"Доступ до: {_format_date_human(expires)}\n"
            f"Теперь можно получать обычный и расширенный совет."
            f"{note}",
            reply_markup=main_menu_inline()
        )
        return

    # 5) Неизвестный payload
    note = f"\nID платежа: {charge_id}" if charge_id else ""
    await message.answer(f"✅ Оплата получена.{note}", reply_markup=main_menu_inline())


# ---------- обратная связь ----------
@router.callback_query(F.data == "menu:feedback")
async def feedback_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    dl_param = f"fb_{cb.from_user.id}"
    if ADMIN_USERNAME:
        url = f"https://t.me/{ADMIN_USERNAME}?start={dl_param}"
    else:
        from config import ADMIN_IDS
        admin_id = next(iter(ADMIN_IDS), None)
        url = f"tg://user?id={admin_id}" if admin_id else "https://t.me/"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написать разработчику", url=url)],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ])

    text = (
        "✉️ Обратная связь\n\n"
        "Нажмите кнопку ниже — откроется мой личный чат. "
        "Напишите ваше сообщение (и нажмите Start, если чат открывается впервые)."
    )
    await _edit_text_or_caption(cb.message, text, reply_markup=kb)


# ---------- глушилка на случай «эхо» старых Reply-кнопок ----------
SILENT_LABELS = {
    "🗂 Выбрать тему", "📝 Свой вопрос", "🎁 Промокод", "👤 Профиль",
    "🤝 Пригласить друга", "🛒 Купить сообщения",
    "Любовь", "Работа", "Судьба", "Саморазвитие",
    "Три карты", "Подкова", "Алхимик", "⬅️ В меню", "🔙 Назад"
}
@router.message(F.text.in_(SILENT_LABELS))
async def swallow_reply_keyboard_echo(message: Message):
    return
