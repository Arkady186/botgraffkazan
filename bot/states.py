"""
Состояния для машины состояний (FSM)
"""
from aiogram.fsm.state import State, StatesGroup


class ReportStates(StatesGroup):
    """Состояния для процесса создания заявки"""
    waiting_for_location = State()
    waiting_for_media = State()
    waiting_for_description = State()


class AdminStates(StatesGroup):
    """Состояния для админ-панели"""
    waiting_for_comment = State()
