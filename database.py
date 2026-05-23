"""
Универсальный модуль работы с базой данных.
Автоматически выбирает PostgreSQL (если задан DATABASE_URL) или SQLite.
"""
from config import USE_POSTGRES, DATABASE_URL

if USE_POSTGRES and DATABASE_URL:
    # Импортируем функции из database_pg
    from database_pg import (
        init_db,
        telegram_id_placeholder_for_vk,
        get_or_create_user_vk,
        get_user_by_telegram_id,
        create_user,
        update_user_anonymous,
        create_report,
        get_report,
        get_reports_for_user,
        get_all_reports,
        update_report_status,
        add_media,
        get_media_for_report,
        get_stats,
        get_all_markers,
        test_connection,
    )
    print("Используется PostgreSQL")
else:
    # Импортируем функции из database_sqlite
    from database_sqlite import (
        init_db,
        telegram_id_placeholder_for_vk,
        get_or_create_user_vk,
        get_user_by_telegram_id,
        create_user,
        update_user_anonymous,
        create_report,
        get_report,
        get_reports_for_user,
        get_all_reports,
        update_report_status,
        add_media,
        get_media_for_report,
        get_stats,
        get_all_markers,
        test_connection,
    )
    print("Используется SQLite")

# Реэкспортируем функции
__all__ = [
    'init_db',
    'telegram_id_placeholder_for_vk',
    'get_or_create_user_vk',
    'get_user_by_telegram_id',
    'create_user',
    'update_user_anonymous',
    'create_report',
    'get_report',
    'get_reports_for_user',
    'get_all_reports',
    'update_report_status',
    'add_media',
    'get_media_for_report',
    'get_stats',
    'get_all_markers',
    'test_connection',
]