"""
Telegram бот: учёт граффити в Казани
"""
import os
import shutil
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, Location, PhotoSize, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from config import (
    BOT_TOKEN, MEDIA_PATH, STATUS_LABELS, TELEGRAM_PROXY,
    STATUS_NEW, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_REJECTED
)
import database as db
from bot.keyboards import (
    get_main_keyboard, get_anonymous_keyboard,
    get_info_keyboard, get_back_keyboard
)
from bot.texts import (
    START_TEXT, ANONYMOUS_TEXT, REPORT_START_TEXT,
    REPORT_LOCATION_TEXT, REPORT_DESCRIPTION_TEXT,
    REPORT_CONFIRM_TEXT, MY_REPORTS_TEXT, REPORT_DETAIL_TEXT,
    INFO_MAIN_TEXT, INFO_GRAFFITI_TEXT, INFO_SYSTEM_TEXT,
    INFO_CONTACTS_TEXT, ERROR_TEXT, CANCEL_TEXT, MEDIA_REQUIRED
)
from bot.states import ReportStates

# Роутер для основных команд
router = Router()


# === Команды ===

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработка команды /start"""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await db.create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
    
    await message.answer(
        START_TEXT,
        reply_markup=get_main_keyboard()
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработка команды /help"""
    await message.answer(
        "ℹ️ Справка:\n\n"
        "📍 Сообщить о граффити — отправить фото с координатами\n"
        "📊 Мои заявки — просмотреть статусы ваших обращений\n"
        "🗺️ Карта — посмотреть карту точек\n"
        "ℹ️ Информация — о проекте и контактах\n"
        "🔒 Анонимность — настроить приватность\n\n"
        "📞 Экстренная помощь: 112"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущего действия"""
    await state.clear()
    await message.answer(CANCEL_TEXT, reply_markup=get_main_keyboard())


# === Основное меню ===

@router.message(F.text == "📍 Сообщить о граффити")
async def report_start(message: Message, state: FSMContext):
    """Начало процесса создания заявки"""
    await state.set_state(ReportStates.waiting_for_location)
    await message.answer(
        REPORT_START_TEXT,
        reply_markup=get_back_keyboard()
    )


@router.message(F.text == "📊 Мои заявки")
async def my_reports(message: Message):
    """Просмотр своих заявок"""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ Сначала нажмите /start")
        return
    
    # Получаем все заявки пользователя
    import aiosqlite
    async with aiosqlite.connect(db.DATABASE_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """SELECT r.*, 
                      (SELECT COUNT(*) FROM media WHERE report_id = r.id) as files_count
               FROM reports r
               WHERE r.user_id = ?
               ORDER BY r.created_at DESC""",
            (user['id'],)
        )
        reports = await cursor.fetchall()
    
    if not reports:
        await message.answer("У вас пока нет заявок.\n\nСоздайте первую заявку через меню!")
        return
    
    # Считаем статистику
    total = len(reports)
    new = sum(1 for r in reports if r['status'] == STATUS_NEW)
    in_progress = sum(1 for r in reports if r['status'] == STATUS_IN_PROGRESS)
    completed = sum(1 for r in reports if r['status'] == STATUS_COMPLETED)
    
    await message.answer(
        MY_REPORTS_TEXT.format(total=total, new=new, in_progress=in_progress, completed=completed)
    )
    
    # Выводим последние 10 заявок
    for report in reports[:10]:
        status_label = STATUS_LABELS.get(report['status'], report['status'])
        created = datetime.fromisoformat(report['created_at']).strftime("%d.%m.%Y %H:%M")
        
        text = (
            f"📋 Заявка #{report['id']}\n"
            f"📍 Координаты: {report['latitude']}, {report['longitude']}\n"
            f"📅 Дата: {created}\n"
            f"Статус: {status_label}\n"
            f"📎 Файлов: {report['files_count']}"
        )
        await message.answer(text)


@router.message(F.text == "🗺️ Карта")
async def show_map(message: Message):
    """Показать карту (ссылка на веб-панель)"""
    from config import get_public_site_origin
    origin = get_public_site_origin()
    await message.answer(
        f"🗺️ Интерактивная карта граффити доступна по ссылке:\n\n"
        f"{origin}/public-map\n\n"
        f"На карте отображаются все зарегистрированные случаи."
    )


@router.message(F.text == "ℹ️ Информация")
async def info_menu(message: Message):
    """Меню информации"""
    await message.answer(
        INFO_MAIN_TEXT,
        reply_markup=get_info_keyboard()
    )


@router.message(F.text == "🔒 Анонимность")
async def anonymous_settings(message: Message):
    """Настройки анонимности"""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ Сначала нажмите /start")
        return
    
    status = "✅ Анонимный режим включён" if user['is_anonymous'] else "❌ Анонимный режим выключен"
    
    await message.answer(
        ANONYMOUS_TEXT.format(status=status),
        reply_markup=get_anonymous_keyboard()
    )


# === Процесс создания заявки ===

@router.message(ReportStates.waiting_for_location, F.location)
async def process_location(message: Message, state: FSMContext):
    """Получение геолокации"""
    location = message.location
    
    await state.update_data(
        latitude=location.latitude,
        longitude=location.longitude
    )
    
    await state.set_state(ReportStates.waiting_for_media)
    await message.answer(
        REPORT_LOCATION_TEXT.format(
            latitude=location.latitude,
            longitude=location.longitude
        ),
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(ReportStates.waiting_for_media, F.photo)
async def process_photo(message: Message, state: FSMContext):
    """Обработка фото"""
    data = await state.get_data()
    media_list = data.get('media', [])
    
    # Сохраняем фото (берём в наилучшем качестве)
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_path = os.path.join(MEDIA_PATH, f"photo_{message.message_id}_{photo.file_id}.jpg")
    
    await message.bot.download_file(file.file_path, file_path)
    
    media_list.append({'type': 'photo', 'file_id': photo.file_id, 'file_path': file_path})
    await state.update_data(media=media_list)
    
    await message.answer("✅ Фото получено! Отправьте ещё или нажмите «✅ Готово»")


@router.message(ReportStates.waiting_for_media, F.video)
async def process_video(message: Message, state: FSMContext):
    """Обработка видео"""
    data = await state.get_data()
    media_list = data.get('media', [])
    
    # Сохраняем видео
    video = message.video
    file = await message.bot.get_file(video.file_id)
    file_path = os.path.join(MEDIA_PATH, f"video_{message.message_id}_{video.file_id}.mp4")
    
    await message.bot.download_file(file.file_path, file_path)
    
    media_list.append({'type': 'video', 'file_id': video.file_id, 'file_path': file_path})
    await state.update_data(media=media_list)
    
    await message.answer("✅ Видео получено! Отправьте ещё или нажмите «✅ Готово»")


@router.message(ReportStates.waiting_for_media, F.text == "✅ Готово")
async def finish_media(message: Message, state: FSMContext):
    """Завершение загрузки медиа и переход к описанию"""
    data = await state.get_data()
    media_list = data.get('media', [])
    
    if not media_list:
        await message.answer(MEDIA_REQUIRED)
        return
    
    await state.set_state(ReportStates.waiting_for_description)
    await message.answer(
        REPORT_DESCRIPTION_TEXT,
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="⏭️ Пропустить")]],
            resize_keyboard=True
        )
    )


@router.message(ReportStates.waiting_for_description, F.text == "⏭️ Пропустить")
async def skip_description(message: Message, state: FSMContext):
    """Пропуск описания"""
    await process_description(message, state)


@router.message(ReportStates.waiting_for_description, F.text)
async def process_description(message: Message, state: FSMContext):
    """Сохранение описания и создание заявки"""
    data = await state.get_data()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    description = message.text if message.text != "⏭️ Пропустить" else None
    
    # Создаём заявку
    report_id = await db.create_report(
        user_id=user['id'],
        latitude=data['latitude'],
        longitude=data['longitude'],
        description=description
    )
    
    # Сохраняем медиа
    for media in data.get('media', []):
        await db.add_media(
            report_id=report_id,
            file_type=media['type'],
            file_path=media['file_path'],
            file_id=media['file_id']
        )
    
    await state.clear()
    
    await message.answer(
        REPORT_CONFIRM_TEXT.format(report_id=report_id),
        reply_markup=get_main_keyboard()
    )


# === Callback query ===

@router.callback_query(F.data == "back")
async def callback_back(callback: CallbackQuery, state: FSMContext):
    """Кнопка назад"""
    await state.clear()
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "anon_yes")
async def callback_anon_yes(callback: CallbackQuery):
    """Включить анонимность"""
    await db.update_user_anonymous(callback.from_user.id, True)
    await callback.message.edit_text(
        ANONYMOUS_TEXT.format(status="✅ Анонимный режим включён"),
        reply_markup=get_anonymous_keyboard()
    )
    await callback.answer("✅ Анонимность включена")


@router.callback_query(F.data == "anon_no")
async def callback_anon_no(callback: CallbackQuery):
    """Выключить анонимность"""
    await db.update_user_anonymous(callback.from_user.id, False)
    await callback.message.edit_text(
        ANONYMOUS_TEXT.format(status="❌ Анонимный режим выключен"),
        reply_markup=get_anonymous_keyboard()
    )
    await callback.answer("❌ Анонимность выключена")


@router.callback_query(F.data.startswith("info_"))
async def callback_info(callback: CallbackQuery):
    """Информационные разделы"""
    if callback.data == "info_graffiti":
        text = INFO_GRAFFITI_TEXT
    elif callback.data == "info_system":
        text = INFO_SYSTEM_TEXT
    elif callback.data == "info_contacts":
        text = INFO_CONTACTS_TEXT
    else:
        return
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard()
    )
    await callback.answer()


# === Запуск бота ===

async def main():
    """Точка входа"""
    # Инициализация БД
    await db.init_db()

    # Создание бота с поддержкой прокси
    from aiogram.client.bot import DefaultBotProperties
    from aiogram.client.session.aiohttp import AiohttpSession

    session = None
    if TELEGRAM_PROXY:
        # Поддержка формата: socks5://host:port или host:port
        if not TELEGRAM_PROXY.startswith("socks5://"):
            proxy_url = f"socks5://{TELEGRAM_PROXY}"
        else:
            proxy_url = TELEGRAM_PROXY
        
        print(f"🔑 Используем прокси: {proxy_url}")
        session = AiohttpSession(proxy=proxy_url)
    else:
        session = AiohttpSession()

    bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties())
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутера
    dp.include_router(router)

    # Запуск с обработкой ошибок
    print("🤖 Бот запущен...")
    
    # Пробуем получить информацию о боте с обработкой ошибок
    try:
        bot_info = await bot.me()
        print(f"💬 Username бота: @{bot_info.username}")
    except Exception as e:
        print(f"⚠️ Не удалось подключиться к Telegram: {type(e).__name__}")
        print("   Проверьте интернет-соединение и токен бота")
        if not TELEGRAM_PROXY:
            print("💡 Возможно, требуется прокси. Добавьте TELEGRAM_PROXY в .env")
        print("   Бот продолжит работу и попытается подключиться при polling...")
    
    print()
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")
        print("Проверьте токен и подключение к интернету")
        if not TELEGRAM_PROXY:
            print("💡 Возможно, требуется прокси. Добавьте TELEGRAM_PROXY в .env")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    import asyncio
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    asyncio.run(main())
