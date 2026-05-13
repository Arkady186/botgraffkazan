"""
Веб-панель: учёт обращений о граффити (Казань)
"""
import os
import json
import asyncio
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware
from typing import Optional, List
import secrets
import uuid

from config import (
    WEB_HOST, WEB_PORT, DATABASE_PATH, MEDIA_PATH,
    STATUS_LABELS, STATUS_NEW, STATUS_IN_PROGRESS,
    STATUS_COMPLETED, STATUS_REJECTED,
    SECRET_KEY, VK_GROUP_PUBLIC_URL,
)
import database as db
import status_notify
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте приложения"""
    await db.init_db()
    yield


# Приложение FastAPI
app = FastAPI(title="Граффити · Казань — панель управления", lifespan=lifespan)

# Middleware для сессий
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Шаблоны и статика
_templates_dir = Path(__file__).resolve().parent / "templates"
_static_dir = Path(__file__).resolve().parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
templates = Jinja2Templates(directory=str(_templates_dir))

# Простая аутентификация
security = HTTPBasic()

# Администраторы (в реальном проекте - из БД)
ADMIN_USERS = {
    "admin": "admin123",  # login: password
    "operator": "operator123"
}


def get_current_user(request: Request):
    """Получить текущего пользователя из сессии"""
    return request.session.get("user")


def check_admin(request: Request):
    """Проверка авторизации"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


# === Публичные страницы ===

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Главная публичная страница"""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "vk_group_url": VK_GROUP_PUBLIC_URL or None},
    )


@app.get("/public-map", response_class=HTMLResponse)
async def public_map(request: Request):
    """Публичная карта (без авторизации)"""
    reports = await db.get_reports_for_map()
    
    markers = []
    for r in reports:
        markers.append({
            "id": r["id"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "status": r["status"],
            "address": r.get("address", ""),
            "description": r.get("description") or "",
            "created_at": r.get("created_at", "")
        })

    return templates.TemplateResponse("map.html", {
        "request": request,
        "markers": json.dumps(markers, ensure_ascii=False),
        "status_labels": STATUS_LABELS
    })


@app.get("/public-report/{report_id}", response_class=HTMLResponse)
async def public_report_page(request: Request, report_id: int):
    """Публичная карточка заявки (без входа) — для ссылок с карты."""
    report = await db.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    media = await db.get_report_media(report_id)
    history = await db.get_status_history(report_id)
    return templates.TemplateResponse(
        "public_report.html",
        {
            "request": request,
            "report": report,
            "media": media,
            "history": history,
            "status_labels": STATUS_LABELS,
        },
    )


# === API для подачи заявок ===

@app.post("/api/submit-report")
async def submit_report(
    latitude: float = Form(...),
    longitude: float = Form(...),
    address: str = Form(default=""),
    description: str = Form(default=""),
    photos: List[UploadFile] = File(default=None)
):
    """API: Создание новой заявки с сайта"""
    try:
        # Создаём заявку от имени "системы" (анонимно)
        # Для сайтовных заявок используем user_id = 0 (специальный ID)
        report_id = await db.create_report(
            user_id=0,  # Специальный ID для заявок с сайта
            latitude=latitude,
            longitude=longitude,
            address=address,
            description=description
        )
        
        # Сохраняем фото
        if photos:
            for photo in photos:
                # Генерируем уникальное имя файла
                file_ext = os.path.splitext(photo.filename)[1] if photo.filename else ".jpg"
                file_name = f"web_{report_id}_{uuid.uuid4().hex}{file_ext}"
                file_path = os.path.join(MEDIA_PATH, file_name)

                # Сохраняем файл
                with open(file_path, "wb") as f:
                    f.write(await photo.read())

                # Добавляем в БД (сохраняем только имя файла для URL)
                await db.add_media(
                    report_id=report_id,
                    file_type="photo",
                    file_path=file_name,  # Сохраняем только имя файла
                    file_id=file_name
                )
        
        return {"success": True, "report_id": report_id}
    
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# === Страницы админ-панели ===

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Страница входа"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, username: str = Form(), password: str = Form()):
    """Обработка входа"""
    if username in ADMIN_USERS and ADMIN_USERS[username] == password:
        request.session["user"] = username
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Неверное имя пользователя или пароль"
    })


@app.get("/logout")
async def logout(request: Request):
    """Выход"""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(check_admin)):
    """Панель управления"""
    # Статистика
    all_reports = await db.get_all_reports(limit=1000)

    # Считаем архивные
    import aiosqlite
    async with aiosqlite.connect(DATABASE_PATH) as db_conn:
        cursor = await db_conn.execute("SELECT COUNT(*) FROM archive")
        row = await cursor.fetchone()
        archived_count = row[0] if row else 0

    stats = {
        "total": len(all_reports),
        "new": sum(1 for r in all_reports if r["status"] == STATUS_NEW),
        "in_progress": sum(1 for r in all_reports if r["status"] == STATUS_IN_PROGRESS),
        "completed": sum(1 for r in all_reports if r["status"] == STATUS_COMPLETED),
        "rejected": sum(1 for r in all_reports if r["status"] == STATUS_REJECTED),
        "archived": archived_count,
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "reports": all_reports[:20],
        "status_labels": STATUS_LABELS
    })


@app.get("/reports", response_class=HTMLResponse)
async def reports_list(request: Request, user: str = Depends(check_admin), status_filter: str = "all"):
    """Список всех заявок"""
    if status_filter == "all":
        reports = await db.get_all_reports(limit=100)
    else:
        reports = await db.get_reports_by_status(status_filter)

    for report in reports:
        media = await db.get_report_media(report["id"])
        report["media"] = media

    return templates.TemplateResponse("reports.html", {
        "request": request,
        "user": user,
        "reports": reports,
        "status_labels": STATUS_LABELS,
        "current_filter": status_filter
    })


@app.get("/report/{report_id}", response_class=HTMLResponse)
async def report_detail(request: Request, report_id: int, user: str = Depends(check_admin)):
    """Детали заявки"""
    report = await db.get_report(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    media = await db.get_report_media(report_id)
    history = await db.get_status_history(report_id)

    user_info = None
    if not report.get("is_anonymous"):
        user_info = {
            "telegram_id": report.get("telegram_id"),
            "username": report.get("username"),
            "first_name": report.get("first_name"),
            "last_name": report.get("last_name")
        }

    return templates.TemplateResponse("report_detail.html", {
        "request": request,
        "user": user,
        "report": report,
        "media": media,
        "history": history,
        "status_labels": STATUS_LABELS,
        "user_info": user_info
    })


@app.post("/report/{report_id}/status")
async def update_report_status(
    request: Request,
    report_id: int,
    new_status: str = Form(),
    comment: str = Form(default=""),
    user: str = Depends(check_admin)
):
    """Обновление статуса заявки"""
    valid_statuses = [STATUS_NEW, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_REJECTED]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Неверный статус")

    existing = await db.get_report(report_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    old_status = existing["status"]

    await db.update_report_status(report_id, new_status, comment=comment)

    if old_status != new_status or (comment and comment.strip()):
        asyncio.create_task(
            status_notify.notify_submitter_status_update(
                report_id, old_status, new_status, comment
            )
        )

    return RedirectResponse(url=f"/report/{report_id}", status_code=303)


@app.post("/report/{report_id}/delete")
async def delete_report(
    request: Request,
    report_id: int,
    user: str = Depends(check_admin)
):
    """Удаление заявки (перемещение в архив)"""
    # Получаем ID админа из пользователей (для простоты используем 0)
    admin_id = 0
    
    success = await db.archive_report(report_id, admin_id)
    
    if success:
        # Запускаем очистку старых записей
        deleted = await db.cleanup_old_archive()
        if deleted > 0:
            print(f"🗑️ Удалено {deleted} старых записей из архива")
    
    return RedirectResponse(url="/reports", status_code=303)


@app.get("/archive", response_class=HTMLResponse)
async def archive_list(request: Request, user: str = Depends(check_admin)):
    """Список архивных заявок"""
    archived = await db.get_archived_reports(limit=100)
    
    # Добавляем медиа для каждой заявки
    for report in archived:
        media = await db.get_archive_media(report["id"])
        report["media"] = media
    
    return templates.TemplateResponse("archive.html", {
        "request": request,
        "user": user,
        "archived": archived,
        "status_labels": STATUS_LABELS
    })


@app.get("/map", response_class=HTMLResponse)
async def map_page(request: Request):
    """Интерактивная карта"""
    reports = await db.get_reports_for_map()

    markers = []
    for r in reports:
        markers.append({
            "id": r["id"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "status": r["status"],
            "address": r.get("address", ""),
            "description": r.get("description") or "",
            "created_at": r.get("created_at", "")
        })

    return templates.TemplateResponse("map.html", {
        "request": request,
        "markers": json.dumps(markers, ensure_ascii=False),
        "status_labels": STATUS_LABELS
    })


@app.get("/api/reports")
async def api_reports(user: str = Depends(check_admin)):
    """API: Получить все заявки"""
    reports = await db.get_all_reports(limit=100)
    return {"reports": reports}


@app.get("/api/markers")
async def api_markers():
    """API: Получить маркеры для карты (публичный доступ)"""
    reports = await db.get_reports_for_map()
    return {"markers": reports}


# === Статические файлы ===

# Монтируем директорию media для доступа к файлам
app.mount("/media", StaticFiles(directory=MEDIA_PATH), name="media")


# === Запуск ===

if __name__ == "__main__":
    import uvicorn
    
    # Инициализация БД
    import asyncio
    asyncio.run(db.init_db())
    
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)
