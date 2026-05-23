"""
Модуль работы с PostgreSQL (альтернатива database.py)
Используется, если задана переменная окружения DATABASE_URL.
"""
import asyncpg
from datetime import datetime
from typing import Optional, List, Dict, Any
from config import DATABASE_URL, STATUS_NEW
import asyncio

# Пул соединений
_pool = None

async def get_pool():
    """Возвращает пул соединений к PostgreSQL (создаёт при первом вызове)"""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return _pool

async def close_pool():
    """Закрывает пул соединений"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

async def init_db():
    """Инициализация базы данных PostgreSQL и создание таблиц"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_anonymous BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Таблица заявок
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                address TEXT,
                description TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        # Таблица медиафайлов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id SERIAL PRIMARY KEY,
                report_id INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (report_id) REFERENCES reports(id)
            )
        """)
        # Таблица статусов (история изменений)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS status_history (
                id SERIAL PRIMARY KEY,
                report_id INTEGER NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                comment TEXT,
                admin_id INTEGER,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (report_id) REFERENCES reports(id)
            )
        """)
        # Таблица архива удалённых заявок
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS archive (
                id SERIAL PRIMARY KEY,
                report_id INTEGER,
                user_id INTEGER,
                latitude REAL,
                longitude REAL,
                address TEXT,
                description TEXT,
                status TEXT,
                deleted_by INTEGER,
                deleted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                original_created_at TIMESTAMPTZ,
                auto_delete_date TIMESTAMPTZ
            )
        """)
        # Таблица медиа архива
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS archive_media (
                id SERIAL PRIMARY KEY,
                archive_id INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (archive_id) REFERENCES archive(id)
            )
        """)
        print("Таблицы PostgreSQL созданы/проверены")

# === Пользователи ===

def telegram_id_placeholder_for_vk(vk_user_id: int) -> int:
    """Пользователи VK хранятся в users.telegram_id как отрицательный числовой id VK."""
    return -abs(int(vk_user_id))

async def get_or_create_user_vk(
    vk_user_id: int,
    username: str = None,
    first_name: str = None,
    last_name: str = None,
) -> dict:
    """Найти или создать запись пользователя, пришедшего из VK."""
    tid = telegram_id_placeholder_for_vk(vk_user_id)
    user = await get_user_by_telegram_id(tid)
    if user:
        return user
    await create_user(tid, username, first_name, last_name, False)
    return await get_user_by_telegram_id(tid)

async def get_user_by_telegram_id(telegram_id: int) -> Optional[dict]:
    """Получить пользователя по Telegram ID"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1",
            telegram_id
        )
        return dict(row) if row else None

async def create_user(telegram_id: int, username: str = None, 
                      first_name: str = None, last_name: str = None,
                      is_anonymous: bool = False) -> int:
    """Создать нового пользователя"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO users (telegram_id, username, first_name, last_name, is_anonymous)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            telegram_id, username, first_name, last_name, is_anonymous
        )
        return row['id']

async def update_user_anonymous(telegram_id: int, is_anonymous: bool):
    """Обновить статус анонимности пользователя"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_anonymous = $1 WHERE telegram_id = $2",
            is_anonymous, telegram_id
        )

# === Заявки ===

async def create_report(user_id: int, latitude: float, longitude: float,
                        address: str = None, description: str = None) -> int:
    """Создать новую заявку"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO reports (user_id, latitude, longitude, address, description)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            user_id, latitude, longitude, address, description
        )
        return row['id']

async def get_report(report_id: int) -> Optional[dict]:
    """Получить заявку по ID (с данными автора для панели)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT r.*, u.telegram_id, u.username, u.first_name, u.last_name, u.is_anonymous
               FROM reports r
               LEFT JOIN users u ON r.user_id = u.id
               WHERE r.id = $1""",
            report_id
        )
        return dict(row) if row else None

async def get_reports_for_user(user_pk: int, limit: int = 15) -> List[dict]:
    """Заявки одного пользователя (последние первыми)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT r.*,
                      (SELECT COUNT(*) FROM media m WHERE m.report_id = r.id) AS files_count
               FROM reports r
               WHERE r.user_id = $1
               ORDER BY r.created_at DESC
               LIMIT $2""",
            user_pk, limit
        )
        return [dict(row) for row in rows]

async def get_all_reports(limit: int = 100, offset: int = 0) -> List[dict]:
    """Все заявки (для панели оператора)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT r.*, u.telegram_id, u.username, u.first_name, u.last_name, u.is_anonymous
               FROM reports r
               LEFT JOIN users u ON r.user_id = u.id
               ORDER BY r.created_at DESC
               LIMIT $1 OFFSET $2""",
            limit, offset
        )
        return [dict(row) for row in rows]

async def update_report_status(report_id: int, new_status: str, admin_id: int = None, comment: str = None):
    """Обновить статус заявки и добавить запись в историю."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Получаем старый статус
            old = await conn.fetchrow("SELECT status FROM reports WHERE id = $1", report_id)
            old_status = old['status'] if old else None
            # Обновляем заявку
            await conn.execute(
                "UPDATE reports SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                new_status, report_id
            )
            # Добавляем запись в историю
            await conn.execute(
                """INSERT INTO status_history (report_id, old_status, new_status, comment, admin_id)
                   VALUES ($1, $2, $3, $4, $5)""",
                report_id, old_status, new_status, comment, admin_id
            )

async def add_media(report_id: int, file_type: str, file_path: str, file_id: str) -> int:
    """Добавить медиафайл к заявке."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO media (report_id, file_type, file_path, file_id)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            report_id, file_type, file_path, file_id
        )
        return row['id']

async def get_media_for_report(report_id: int) -> List[dict]:
    """Получить все медиафайлы заявки."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM media WHERE report_id = $1 ORDER BY created_at",
            report_id
        )
        return [dict(row) for row in rows]

# === Статистика ===

async def get_stats() -> Dict[str, int]:
    """Статистика по заявкам."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM reports")
        new = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'new'")
        progress = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'in_progress'")
        completed = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'completed'")
        return {
            'total': total,
            'new': new,
            'in_progress': progress,
            'completed': completed
        }

async def get_all_markers() -> List[dict]:
    """Все заявки для отображения на карте."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, latitude, longitude, status, address, description
               FROM reports
               WHERE latitude IS NOT NULL AND longitude IS NOT NULL"""
        )
        return [dict(row) for row in rows]

# === Утилиты ===

async def test_connection():
    """Тест подключения к базе."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            print(f"Подключено к PostgreSQL: {version[:50]}")
            return True
    except Exception as e:
        print(f"Ошибка подключения к PostgreSQL: {e}")
        return False

if __name__ == "__main__":
    # Тест
    asyncio.run(init_db())
    asyncio.run(test_connection())