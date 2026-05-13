"""
Модуль работы с базой данных SQLite
"""
import aiosqlite
from datetime import datetime
from typing import Optional, List
from config import DATABASE_PATH, STATUS_NEW


async def init_db():
    """Инициализация базы данных и создание таблиц"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_anonymous BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица заявок
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                address TEXT,
                description TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Таблица медиафайлов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (report_id) REFERENCES reports(id)
            )
        """)
        
        # Таблица статусов (история изменений)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                comment TEXT,
                admin_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (report_id) REFERENCES reports(id)
            )
        """)

        # Таблица архива удалённых заявок
        await db.execute("""
            CREATE TABLE IF NOT EXISTS archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER,
                user_id INTEGER,
                latitude REAL,
                longitude REAL,
                address TEXT,
                description TEXT,
                status TEXT,
                deleted_by INTEGER,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                original_created_at TIMESTAMP,
                auto_delete_date TIMESTAMP
            )
        """)

        # Таблица медиа архива
        await db.execute("""
            CREATE TABLE IF NOT EXISTS archive_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_id INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (archive_id) REFERENCES archive(id)
            )
        """)

        await db.commit()


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
    row = await get_user_by_telegram_id(tid)
    if row:
        return row
    await create_user(tid, username, first_name, last_name, False)
    return await get_user_by_telegram_id(tid)


async def get_user_by_telegram_id(telegram_id: int) -> Optional[dict]:
    """Получить пользователя по Telegram ID"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_user(telegram_id: int, username: str = None, 
                      first_name: str = None, last_name: str = None,
                      is_anonymous: bool = False) -> int:
    """Создать нового пользователя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO users (telegram_id, username, first_name, last_name, is_anonymous)
               VALUES (?, ?, ?, ?, ?)""",
            (telegram_id, username, first_name, last_name, is_anonymous)
        )
        await db.commit()
        return cursor.lastrowid


async def update_user_anonymous(telegram_id: int, is_anonymous: bool):
    """Обновить статус анонимности пользователя"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET is_anonymous = ? WHERE telegram_id = ?",
            (is_anonymous, telegram_id)
        )
        await db.commit()


# === Заявки ===

async def create_report(user_id: int, latitude: float, longitude: float,
                        address: str = None, description: str = None) -> int:
    """Создать новую заявку"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO reports (user_id, latitude, longitude, address, description)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, latitude, longitude, address, description)
        )
        await db.commit()
        return cursor.lastrowid


async def get_report(report_id: int) -> Optional[dict]:
    """Получить заявку по ID (с данными автора для панели)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT r.*, u.telegram_id, u.username, u.first_name, u.last_name, u.is_anonymous
               FROM reports r
               LEFT JOIN users u ON r.user_id = u.id
               WHERE r.id = ?""",
            (report_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_reports_for_user(user_pk: int, limit: int = 15) -> List[dict]:
    """Заявки одного пользователя (последние первыми)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT r.*,
                      (SELECT COUNT(*) FROM media m WHERE m.report_id = r.id) AS files_count
               FROM reports r
               WHERE r.user_id = ?
               ORDER BY r.created_at DESC
               LIMIT ?""",
            (user_pk, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_reports(limit: int = 100, offset: int = 0) -> List[dict]:
    """Получить все заявки с пагинацией"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT r.*, u.telegram_id, u.username, u.first_name, u.last_name, u.is_anonymous
               FROM reports r
               LEFT JOIN users u ON r.user_id = u.id
               ORDER BY r.created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_reports_by_status(status: str) -> List[dict]:
    """Получить заявки по статусу"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT r.*, u.telegram_id, u.username, u.first_name, u.last_name, u.is_anonymous
               FROM reports r
               LEFT JOIN users u ON r.user_id = u.id
               WHERE r.status = ?
               ORDER BY r.created_at DESC""",
            (status,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_report_status(report_id: int, status: str, 
                                admin_id: int = None, comment: str = None):
    """Обновить статус заявки"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Получаем текущий статус
        cursor = await db.execute(
            "SELECT status FROM reports WHERE id = ?",
            (report_id,)
        )
        row = await cursor.fetchone()
        old_status = row[0] if row else None
        
        # Обновляем статус
        await db.execute(
            """UPDATE reports 
               SET status = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (status, report_id)
        )
        
        # Записываем в историю
        await db.execute(
            """INSERT INTO status_history (report_id, old_status, new_status, comment, admin_id)
               VALUES (?, ?, ?, ?, ?)""",
            (report_id, old_status, status, comment, admin_id)
        )
        
        await db.commit()


async def get_report_media(report_id: int) -> List[dict]:
    """Получить все медиафайлы заявки"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM media WHERE report_id = ?",
            (report_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def add_media(report_id: int, file_type: str, file_path: str, file_id: str) -> int:
    """Добавить медиафайл к заявке"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO media (report_id, file_type, file_path, file_id)
               VALUES (?, ?, ?, ?)""",
            (report_id, file_type, file_path, file_id)
        )
        await db.commit()
        return cursor.lastrowid


async def get_status_history(report_id: int) -> List[dict]:
    """Получить историю статусов заявки"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM status_history 
               WHERE report_id = ?
               ORDER BY created_at DESC""",
            (report_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_reports_for_map() -> List[dict]:
    """Получить заявки для отображения на карте"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT id, latitude, longitude, status, address, description, created_at
               FROM reports
               ORDER BY created_at DESC"""
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# === Архив ===

async def archive_report(report_id: int, deleted_by: int = None):
    """Переместить заявку в архив"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Получаем заявку
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,)
        )
        report = await cursor.fetchone()
        
        if not report:
            return False
        
        report = dict(report)
        
        # Вычисляем дату автоудаления (30 дней)
        from datetime import datetime, timedelta
        auto_delete_date = datetime.now() + timedelta(days=30)
        
        # Сохраняем в архив
        await db.execute("""
            INSERT INTO archive (report_id, user_id, latitude, longitude, address, 
                               description, status, deleted_by, original_created_at, auto_delete_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report['id'],
            report['user_id'],
            report['latitude'],
            report['longitude'],
            report.get('address'),
            report.get('description'),
            report['status'],
            deleted_by,
            report['created_at'],
            auto_delete_date.isoformat()
        ))
        
        # Копируем медиа в архив
        cursor = await db.execute(
            "SELECT * FROM media WHERE report_id = ?",
            (report_id,)
        )
        media_rows = await cursor.fetchall()
        
        archive_id = await db.execute("SELECT last_insert_rowid()")
        archive_id = (await archive_id.fetchone())[0]
        
        for media in media_rows:
            await db.execute("""
                INSERT INTO archive_media (archive_id, file_type, file_path, file_id)
                VALUES (?, ?, ?, ?)
            """, (archive_id, media['file_type'], media['file_path'], media['file_id']))
        
        # Удаляем заявку
        await db.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        await db.commit()
        
        return True


async def get_archived_reports(limit: int = 100) -> List[dict]:
    """Получить архивные заявки"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM archive
               ORDER BY deleted_at DESC
               LIMIT ?""",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def cleanup_old_archive():
    """Удалить старые заявки из архива (старше 30 дней)"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Удаляем медиа архивных записей
        await db.execute("""
            DELETE FROM archive_media
            WHERE archive_id IN (
                SELECT id FROM archive
                WHERE auto_delete_date < datetime('now')
            )
        """)
        
        # Удаляем старые записи
        cursor = await db.execute("""
            DELETE FROM archive
            WHERE auto_delete_date < datetime('now')
        """)
        deleted = cursor.rowcount
        await db.commit()
        
        return deleted


async def get_archive_media(archive_id: int) -> List[dict]:
    """Получить медиа архивной заявки"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM archive_media WHERE archive_id = ?",
            (archive_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_user_telegram_id_by_report(report_id: int) -> Optional[int]:
    """Получить Telegram ID пользователя по заявке"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """SELECT u.telegram_id
               FROM reports r
               JOIN users u ON r.user_id = u.id
               WHERE r.id = ?""",
            (report_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None
