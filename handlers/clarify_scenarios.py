# handlers/clarify_scenarios.py
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from services.clarify_scenarios import get_theme, build_scenario_context
from keyboards_inline import scenario_inline, spread_inline  # spread_inline у вас уже есть

router = Router(name="clarify_scenarios")

# 1) Перехватываем выбор темы и показываем список сценариев
@router.callback_query(F.data.startswith("theme:"))
async def on_theme_selected(cb: CallbackQuery, state: FSMContext):
    theme_id = cb.data.split(":")[1]
    theme = get_theme(theme_id, fallback_title="Тема")

    # сохраняем выбранную тему и обнуляем выбранный сценарий
    await state.update_data(theme_id=theme.theme_id, scenario_id=None, scenario_ctx=None)

    # если для темы нет сценариев — ведем по старому потоку: сразу к раскладам
    if not theme.scenarios:
        await cb.message.edit_text("Выберите расклад:", reply_markup=spread_inline())
        await cb.answer()
        return

    # показываем сценарии
    await cb.message.edit_text(
        f"Тема: {theme.title}\nВыберите уточняющий сценарий:",
        reply_markup=scenario_inline(theme.theme_id, theme.scenarios)
    )
    await cb.answer()

# 2) Пользователь выбрал сценарий: сохраняем контекст и ведём к раскладам
@router.callback_query(F.data.startswith("scen:select:"))
async def on_scenario_selected(cb: CallbackQuery, state: FSMContext):
    try:
        _, _, theme_id, scen_id = cb.data.split(":")
    except ValueError:
        await cb.answer("Некорректные данные", show_alert=True)
        return

    theme = get_theme(theme_id, fallback_title="Тема")
    scen = next((s for s in theme.scenarios if s.id == scen_id), None)
    if not scen:
        await cb.answer("Сценарий не найден", show_alert=True)
        return

    scenario_ctx = build_scenario_context(theme.title, scen.title, scen.bullets)
    await state.update_data(scenario_id=scen_id, scenario_ctx=scenario_ctx)

    await cb.message.edit_text(
        f"Вы выбрали: {scen.title}\nТеперь выберите расклад:",
        reply_markup=spread_inline()
    )
    await cb.answer()
