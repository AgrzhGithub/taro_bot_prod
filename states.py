from aiogram.fsm.state import StatesGroup, State

class TarotStates(StatesGroup):
    choosing_theme = State()
    choosing_spread = State()
    