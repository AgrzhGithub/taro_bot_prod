# handlers/inline_flow.py
from services import tarot_ai
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardRemove, PreCheckoutQuery, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup,
    FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import os
from datetime import datetime, date

from sqlalchemy import select

from keyboards_inline import (
    main_menu_inline, theme_inline, spread_inline, buy_inline, back_to_menu_inline, promo_inline, advice_inline_limits,
    advice_buy_inline
)
from config import ADMIN_USERNAME
from services.tarot_ai import draw_cards, gpt_make_prediction, merge_with_scenario, gpt_make_advice_from_yandex_answer
from services.billing import (
    ensure_user, get_user_balance, redeem_promocode,
    build_invite_link, grant_credits, activate_pass_month,
    spend_one_or_pass,           # использовать для списаний только при раскладах/вопросах
    pass_is_active               # проверка активности PASS без списаний
)
from handlers.daily_card import _send_daily_media_with_caption
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


# ---------- старт/меню/хелп ----------
@router.message(CommandStart())
async def start_inline(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username)
    welcome = (
        "🔮 Добро пожаловать в волшебный мир Таро!\n\n"
        "Перед вами не просто бот, а Ваш главный помощник в мире Таро. "
        "Бот на основе искуственного интеллекта, обученного на лучших книгах о предсказаниях по картам Таро.\n\n"

        "✨ Как работает магия:\n"
        "Прежде чем задать вопрос, позвольте себе несколько мгновений покоя. Сделайте глубокий вдох, "
        "отпустите тревоги и сосредоточьтесь на своей интуиции. Чем спокойнее будет ваш разум, тем яснее заговорят карты"
        "1) Выберите интересующую вас тему: любовь, отношения, будущее, работа или иной жизненный вопрос.\n"
        "2) Я раскрою перед вами карты — от простых трёхкартных раскладов до древних схем вроде «Подковы» или «Алхимика».\n"
        "3) В конце каждого расклада вы получите «Итог» — суть послания карт. "
        "А для тех, кто хочет большего, есть ✨Советы: одна или три карты, которые укажут направление действий.\n\n"

        "🌙 Бесплатные возможности:\n"
        "— «🗓 Карта дня» — каждый день вы можете получать особую карту, "
        "которая задаёт тон и настроение вашему пути. "
        "С ней можно прожить день осознанно и увидеть скрытые подсказки судьбы.\n\n"

        "💎 Дополнительно:\n"
        "— У вас есть возможность активировать промокод и получить бесплатный расклад.\n"
        "— Вы можете приобрести доступ к советам или оформить подписку, открывающую "
        "все магические функции бота.\n\n"

        "⚡️ В любой момент вы можете вернуться в главное меню и начать новый путь. "
        "Карты уже ждут вас — задайте вопрос, и они ответят так, как не ответит никто другой…\n\n"

        "🔮 Пусть Вас ждет как можно больше положительных новостей и эмоций! 😊"
        
    )


    sent = await _send_daily_media_with_caption(message, None, welcome)
    if not sent:
        await message.answer(welcome)

    #await message.answer(welcome, reply_markup=ReplyKeyboardRemove())
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
        await cb.message.edit_text(txt, reply_markup=main_menu_inline())
    else:
        await cb.message.edit_reply_markup(reply_markup=main_menu_inline())


@router.callback_query(F.data == "nav:menu")
async def nav_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await cb.message.edit_text("📋 Главное меню:", reply_markup=main_menu_inline())


# ---------- темы/расклады ----------
@router.callback_query(F.data == "menu:theme")
async def menu_theme(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await cb.message.edit_text("Выберите тему:", reply_markup=theme_inline())


@router.callback_query(F.data.startswith("theme:"))
async def pick_theme(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    theme = cb.data.split(":", 1)[1]
    await state.update_data(theme=theme)
    await cb.message.edit_text(f"Тема: {theme}\nВыберите расклад:", reply_markup=spread_inline())


@router.callback_query(F.data == "nav:theme")
async def back_to_theme(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.edit_text("Выберите тему:", reply_markup=theme_inline())


@router.callback_query(F.data.startswith("spread:"))
async def pick_spread(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    spread = cb.data.split(":", 1)[1]
    data = await state.get_data()

    theme = data.get("theme", "Общая")
    scenario_ctx = data.get("scenario_ctx")  # сохраняем уточнение темы, если было
    # ВОПРОС ПОЛЬЗОВАТЕЛЯ: берём из FSM (как ты его туда клал при вводе)
    user_question = (
        data.get("user_question")
        or data.get("question")
        or data.get("last_question")
        or ""
    )

    # списываем доступ — без изменений
    ok, src = await spend_one_or_pass(cb.from_user.id)
    if not ok:
        if src == "pass_rate_limit":
            await cb.message.edit_text("⏳ Слишком часто. Попробуйте через минуту.", reply_markup=main_menu_inline())
        elif src == "pass_day_limit":
            await cb.message.edit_text("📅 Дневной лимит подписки исчерпан. Попробуйте завтра.", reply_markup=main_menu_inline())
        else:
            await cb.message.edit_text("❌ Нет доступных сообщений. Купите пакет или оформите подписку 🛒", reply_markup=main_menu_inline())
        await state.clear()
        return

    # тягаем карты под выбранный расклад — как у тебя
    if spread == "Три карты":
        cards = draw_cards(3)
    elif spread == "Подкова":
        cards = draw_cards(7)
    elif spread == "Алхимик":
        cards = draw_cards(4)
    else:
        cards = draw_cards(3)

    names = _card_names(cards)                 # список имён для сохранения и совета
    cards_list = ", ".join(names)              # строка — как ты сейчас передаёшь в gpt
    await cb.message.edit_text(f"🎴 Расклад: {spread}\n🃏 Карты: {cards_list}\n\n🔮 Делаю толкование...")

    try:
        # ВАЖНО: в question передаём ВОПРОС ПОЛЬЗОВАТЕЛЯ, а инструкции остаются в prompt внутри gpt-функции
        prediction = await gpt_make_prediction(
            question=user_question,
            theme=theme,
            spread=spread,
            cards_list=cards_list,     # если твоя функция принимает строку — оставляем строку
            scenario_ctx=scenario_ctx,
        )
    except Exception as e:
        prediction = f"⚠️ Не удалось получить толкование: {e}"

    # лог в БД — как было
    user = await ensure_user(cb.from_user.id, cb.from_user.username)
    async with SessionLocal() as s:
        s.add(models.SpreadLog(user_id=user.id, theme=theme, spread=spread, cards={"cards": names}, cost=1))
        await s.commit()

    # извлекаем Итог, сохраняем контекст для кнопок «Совет»
    itog = _extract_itog(prediction)
    await state.update_data(
        last_theme=theme,
        last_spread=spread,
        last_question=user_question,   # <-- сохраняем определённый вопрос
        last_cards=names,              # список имён карт (нужен для совета)
        last_itog=itog,
        last_scenario=scenario_ctx,
        last_prediction_text=prediction,  # <-- ВАЖНО: сохраняем полный текст предсказания
    )

    # показываем две кнопки "Обычный совет (1)" и "Расширенный совет (3)"
    await cb.message.edit_text(prediction, reply_markup=advice_inline_limits(True, True))

    # ВАЖНО: НЕ ОЧИЩАЕМ state здесь, иначе советы не сработают
    # await state.clear()  # <-- не очищаем


@router.callback_query(F.data.in_({
    "advice:1", "advice:3",          # из ветки «тем»
    "ownq:advice:1", "ownq:advice:3" # из ветки «Свой вопрос»
}))
async def advice_handler(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    # единый парсер
    data_str = cb.data
    # допускаем оба формата: "advice:1" и "ownq:advice:1"
    is_one = data_str.endswith(":1")
    advice_count = 1 if is_one else 3

    # проверка подписки — как и раньше
    has_pass = await pass_is_active(cb.from_user.id)

    # 3 карты — только по подписке
    if advice_count == 3 and not has_pass:
        await cb.message.edit_text(
            "🔒 Расширенный совет (3 карты) доступен по подписке.\n"
            "Оформите 30-дневный доступ и сможете пользоваться как обычным, так и расширенным советом.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оформить подписку — 599₽", callback_data="buy:pass30:59900")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ])
        )
        return

    # 1 карта — если нет подписки, показываем оплату
    if advice_count == 1 and not has_pass:
        await cb.message.edit_text(
            "🧭 Обычный совет — разовый платёж.\n"
            "Нажмите кнопку ниже, чтобы оплатить и получить совет.",
            reply_markup=advice_buy_inline(ADVICE_ONE_PRICE_KOPECKS)
        )
        return

    # подписка активна — генерим совет сразу (1 или 3 карты)
    data = await state.get_data()
    yandex_answer = (cb.message.text or data.get("last_prediction_text") or "").strip()

    try:
        advice_cards = draw_cards(advice_count)
        advice_card_names = [c["name"] for c in advice_cards]
    except Exception:
        advice_card_names = []

    try:
        advice_text = await gpt_make_advice_from_yandex_answer(
            yandex_answer_text=yandex_answer,
            advice_cards_list=advice_card_names,
            advice_count=advice_count,
        )
    except Exception as e:
        advice_text = f"⚠️ Не удалось получить совет: {e}"

    # после 1 карты оставляем 3; после 3 — скрываем обе
    if is_one:
        new_kb = advice_inline_limits(allow_one=False, allow_three=True)
    else:
        new_kb = advice_inline_limits(allow_one=False, allow_three=False)

    await cb.message.edit_text(advice_text, reply_markup=new_kb)


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
    await cb.message.edit_text(hint, reply_markup=back_to_menu_inline())


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

    # ⬇️ ВАЖНО: сохраняем контекст для последующих советов и оплат
    await state.update_data(
        user_question=question,
        last_question=question,
        last_cards=names,
        last_spread="custom",
        last_theme="Пользовательский вопрос",
        last_itog=_extract_itog(prediction),
        last_prediction_text=prediction,  # <-- ключевая строка
    )

    # Показываем те же кнопки советов, что и в ветке «тем»
    await message.answer(prediction, reply_markup=advice_inline_limits(allow_one=True, allow_three=True))
    # state НЕ очищаем, советы/оплата используют сохранённые данные
    # await state.clear()


# ---------- промокод ----------
@router.callback_query(F.data == "menu:promo")
async def promo_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(PromoFSM.waiting_code)
    await cb.message.edit_text("Введите промокод сообщением ⬇️", reply_markup=back_to_menu_inline())


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
    balance = await get_user_balance(cb.from_user.id)

    # НИЧЕГО не списываем здесь.
    is_active = await pass_is_active(cb.from_user.id)
    pass_line = "🎫 Подписка не активна"
    if is_active:
        expires = await _get_pass_expiry_by_tg(cb.from_user.id)
        if expires:
            pass_line = f"🎫 Подписка активна до {_format_date_human(expires)}"

    link = build_invite_link(user.invite_code)
    txt = (f"👤 Ваш профиль\n\n"
           f"💰 Баланс: {balance} сообщений\n"
           f"{pass_line}\n\n"
           f"🔗 Ваш реферальный код: {user.invite_code}\n"
           f"▶️ Ссылка для приглашений:\n{link}")
    await cb.message.edit_text(txt, reply_markup=promo_inline())


# ---------- покупка (кредиты + PASS + разовый совет) ----------
PROVIDER_TOKEN = os.getenv("PAYMENTS_PROVIDER_TOKEN")
CURRENCY = os.getenv("CURRENCY", "RUB")
ADVICE_ONE_PRICE_KOPECKS = int(os.getenv("ADVICE_ONE_PRICE_KOPECKS", "9900"))  # 99₽ по умолчанию

@router.callback_query(F.data == "menu:buy")
async def buy_menu(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("Выберите пакет:", reply_markup=buy_inline())


@router.callback_query(F.data.startswith("buy:"))
async def buy_pick(cb: CallbackQuery, bot: Bot):
    await cb.answer()
    if not PROVIDER_TOKEN:
        await cb.message.edit_text("⚠️ Платёжный провайдер не настроен. Добавьте PAYMENTS_PROVIDER_TOKEN в .env", reply_markup=main_menu_inline())
        return

    parts = cb.data.split(":")
    kind = parts[1]  # "credits" | "pass30" | "advice1"
    print(parts)

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
    elif kind == "advice1":  # <<< разовый платёж за обычный совет
        amount = int(parts[2])
        title = f"Обычный совет (1 карта) — {amount // 100}₽"
        payload = f"advice1_{amount}"
        description = "Разовый платёж за обычный совет (1 карта)"
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
    payload = sp.invoice_payload
    currency = sp.currency or CURRENCY
    total_amount = sp.total_amount
    charge_id = getattr(sp, "provider_payment_charge_id", None)

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

    # --- разовый платёж за обычный совет ---
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

        # после разового совета предлагаем расширенный по подписке
        await message.answer(
            advice_text,
            reply_markup=advice_inline_limits(allow_one=False, allow_three=True)
        )
        return
    # --- /разовый совет ---

    # пакеты сообщений
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

    # подписка PASS
    if payload.startswith("pass30_"):
        expires = await activate_pass_month(user.id, message.from_user.id, plan="pass_unlim")
        await mark_purchase_credited(purchase_id)
        bal = await get_user_balance(message.from_user.id)
        note = f"\nID платежа: {charge_id}" if charge_id else ""
        await message.answer(
            f"✅ Подписка на 30 дней активирована.\nДоступ до: {_format_date_human(expires)}\n"
            f"Теперь можно получать обычный и расширенный совет.",
            reply_markup=main_menu_inline()
        )
        return

    await message.answer("✅ Оплата получена.", reply_markup=main_menu_inline())


# ---------- обратная связь ----------
@router.callback_query(F.data == "menu:feedback")
async def feedback_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()

    # deep-link, чтобы у тебя в ЛС был старт с параметром пользователя
    # ты увидишь его как /start fb_<tg_id>
    dl_param = f"fb_{cb.from_user.id}"
    if ADMIN_USERNAME:
        url = f"https://t.me/{ADMIN_USERNAME}?start={dl_param}"
    else:
        # fallback: открыть профиль по ID (работает не во всех клиентах, но часто ок)
        # Лучше всё же завести публичный username.
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
    await cb.message.edit_text(text, reply_markup=kb)


def _extract_itog(text: str) -> str:
    """
    Возвращает текст раздела 'Итог' из сгенерированного ответа.
    Если 'Итог' не найден, возвращает пустую строку.
    """
    if not text:
        return ""
    # Ищем строку, начинающуюся на "Итог"
    lines = text.splitlines()
    itog_idx = next((i for i, line in enumerate(lines) if line.strip().lower().startswith("итог")), None)
    if itog_idx is None:
        # иногда модель пишет "Итог — ..." без двоеточия
        itog_idx = next((i for i, line in enumerate(lines) if "итог" in line.strip().lower()), None)
    if itog_idx is None:
        return ""

    # Берем всё после строки с "Итог"
    tail = [s for s in lines[itog_idx+1:] if s.strip()]
    return " ".join(tail).strip()


# ---------- глушилка на случай «эхо» старых Reply-кнопок ----------
SILENT_LABELS = {
    "🗂 Выбрать тему","📝 Свой вопрос","🎁 Промокод","👤 Профиль",
    "🤝 Пригласить друга","🛒 Купить сообщения",
    "Любовь","Работа","Судьба","Саморазвитие",
    "Три карты","Подкова","Алхимик","⬅️ В меню","🔙 Назад"
}
@router.message(F.text.in_(SILENT_LABELS))
async def swallow_reply_keyboard_echo(message: Message):
    return
