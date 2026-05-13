"""
Клавиатуры для бота
"""
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основное меню пользователя"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Сообщить о граффити")],
            [KeyboardButton(text="📊 Мои заявки"),
             KeyboardButton(text="🗺️ Карта")],
            [KeyboardButton(text="ℹ️ Информация"),
             KeyboardButton(text="🔒 Анонимность")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_anonymous_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора анонимности"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Анонимно", callback_data="anon_yes")],
            [InlineKeyboardButton(text="❌ Не анонимно", callback_data="anon_no")]
        ]
    )
    return keyboard


def get_report_status_keyboard(report_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для смены статуса заявки (админ)"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏳ В работе", callback_data=f"status_{report_id}_in_progress")],
            [InlineKeyboardButton(text="✅ Завершена", callback_data=f"status_{report_id}_completed")],
            [InlineKeyboardButton(text="❌ Отклонена", callback_data=f"status_{report_id}_rejected")]
        ]
    )
    return keyboard


def get_info_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для раздела информации"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏙️ Граффити и город", callback_data="info_graffiti")],
            [InlineKeyboardButton(text="📋 Как работает система", callback_data="info_system")],
            [InlineKeyboardButton(text="📞 Контакты служб", callback_data="info_contacts")]
        ]
    )
    return keyboard


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка назад"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back")]
        ]
    )
    return keyboard
