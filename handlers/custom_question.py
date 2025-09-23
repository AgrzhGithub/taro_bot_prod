from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from services.billing import spend_one_credit
from services.tarot_ai import draw_cards, gpt_make_prediction
from db import SessionLocal, models
from keyboards import main_menu, custom_question_keyboard

router = Router()

class CustomQuestionFSM(StatesGroup):
    waiting_for_question = State()


@router.message(F.text == "📝 Свой вопрос")
async def ask_custom_question(message: Message, state: FSMContext):
    await message.answer("Введите свой вопрос:", reply_markup=custom_question_keyboard)
    await state.set_state(CustomQuestionFSM.waiting_for_question)


@router.message(CustomQuestionFSM.waiting_for_question, F.text == "⬅️ В меню")
async def to_main_menu(message: Message, state: FSMContext):
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu)  # Возвращаем main_menu
    await state.clear()


@router.message(CustomQuestionFSM.waiting_for_question, F.text)
async def process_custom_question(message: Message, state: FSMContext):
    question = message.text.strip()

    # Проверяем баланс
    ok = await spend_one_credit(message.from_user.id)
    if not ok:
        await message.answer("❌ У вас нет доступных сообщений. Пополните баланс 🛒", reply_markup=main_menu)
        await state.clear()
        return

    # Генерируем предсказание
    cards = draw_cards(3)
    prediction = await gpt_make_prediction(question, cards)

    # Логируем в БД
    async with SessionLocal() as session:
        log = models.SpreadLog(
            user_id=message.from_user.id,
            question=question,
            spread="custom",
            cards={"cards": cards},
            cost=1,
        )
        session.add(log)
        await session.commit()

    await message.answer(prediction, reply_markup=main_menu)
    await state.clear()