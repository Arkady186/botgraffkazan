"""
VK-бот: заявки о граффити в ту же SQLite и MEDIA, что у Telegram и сайта.
Пользователь VK хранится в users.telegram_id как отрицательный числовой id VK.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from urllib.parse import quote
from urllib.request import Request, urlopen

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

UA_HTTP = "GraffitiKazanVKBot/1.0 (+vk community)"

STATES: dict[int, dict] = {}

WELCOME_TEXT = (
    "🎨 *Привет! Бот учёта граффити в Казани.*\n\n"
    "Мы против несанкционированных рисунков и надписей на домах, заборах и в общественных местах — вместе делаем город аккуратнее.\n\n"
    "📍 *Что можно сделать:*\n"
    "• Сообщить о граффити (фото → *✅ Готово* → геолокация или адрес → комментарий)\n"
    "• Открыть *Мои заявки*\n"
    "• Прочитать *Информация*\n\n"
    "Заявки из VK, сайта и Telegram попадают в одну базу и на карту.\n\n"
    "📞 *Экстренная помощь:* 112\n\n"
    "Нажми *📍 Сообщить о граффити* и следуй шагам."
)

INFO_TEXT = (
    "ℹ️ *О проекте*\n\n"
    "Сервис собирает обращения о несанкционированном граффити в Казани: фото, координаты и описание.\n\n"
    "📊 Данные из VK сохраняются в ту же базу, что и с сайта — точки видны на публичной карте.\n\n"
    "Это помогает службам ориентироваться по адресам и фиксировать работу на объектах."
)


def load_vk_user_profile(vk, uid: int) -> dict:
    try:
        res = vk.users.get(user_ids=uid, fields=["screen_name"]) or []
        u = res[0] if res else {}
        sn = u.get("screen_name")
        return {
            "vk_user_id": uid,
            "username": str(sn) if sn else None,
            "first_name": u.get("first_name"),
            "last_name": u.get("last_name"),
        }
    except Exception:
        return {"vk_user_id": uid, "username": None, "first_name": None, "last_name": None}


def _norm(txt: str) -> str:
    return (txt or "").lower().strip()


def create_main_keyboard() -> str:
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("📍 Сообщить о граффити", color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button("📊 Мои заявки", color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button("ℹ️ Информация", color=VkKeyboardColor.PRIMARY)
    return keyboard.get_keyboard()


def create_back_keyboard() -> str:
    keyboard = VkKeyboard(one_time=True)
    keyboard.add_button("⬅️ Назад", color=VkKeyboardColor.SECONDARY)
    return keyboard.get_keyboard()


def create_media_keyboard() -> str:
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("✅ Готово", color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button("⬅️ Назад", color=VkKeyboardColor.SECONDARY)
    return keyboard.get_keyboard()


def create_desc_keyboard() -> str:
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("⏭️ Пропустить", color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button("⬅️ Назад", color=VkKeyboardColor.SECONDARY)
    return keyboard.get_keyboard()


def largest_photo_url(photo: dict) -> str | None:
    sizes = photo.get("sizes") or []
    if not sizes:
        return photo.get("url_orig") or photo.get("url")
    best = max(sizes, key=lambda s: int(s.get("width", 0)) * int(s.get("height", 0)))
    return best.get("url")


def download_url_to_file(url: str, dest_path: str) -> None:
    req = Request(url, headers={"User-Agent": UA_HTTP})
    with urlopen(req, timeout=90) as resp:
        body = resp.read()
    d = os.path.dirname(dest_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(body)


def vk_geo_lat_lon(geo: dict | None) -> tuple[float, float] | None:
    if not geo:
        return None
    c = geo.get("coordinates")
    if isinstance(c, str):
        parts = re.split(r"[\s,]+", c.strip())
        if len(parts) >= 2:
            return float(parts[0]), float(parts[1])
        return None
    if isinstance(c, dict):
        la = c.get("latitude") or c.get("lat")
        lo = c.get("longitude") or c.get("long") or c.get("lng") or c.get("lon")
        if la is not None and lo is not None:
            return float(la), float(lo)
    return None


def geocode_address_osm(query: str) -> tuple[float, float, str] | None:
    def fetch(q: str):
        req = Request(
            f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1&countrycodes=ru&lang=ru",
            headers={"User-Agent": UA_HTTP},
        )
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            return None
        item = data[0]
        return float(item["lat"]), float(item["lon"]), item.get("display_name", "") or ""

    q_primary = quote(f"{query.strip()}, Казань, Татарстан, Россия", safe="")
    res = fetch(q_primary)
    if res:
        return res
    res2 = fetch(quote(query.strip(), safe=""))
    return res2


async def finalize_report(state: dict, description: str | None) -> int:
    import database as db

    user = await db.get_or_create_user_vk(**state["vk_profile"])
    report_id = await db.create_report(
        user_id=user["id"],
        latitude=state["latitude"],
        longitude=state["longitude"],
        address=state.get("address_text"),
        description=description,
    )
    for item in state.get("photos", []):
        fn = os.path.basename(item["file_path"])
        await db.add_media(
            report_id=report_id,
            file_type="photo",
            file_path=fn,
            file_id=item["file_id"],
        )

    return report_id


async def compose_my_reports(prof: dict) -> str:
    import database as db
    from config import STATUS_LABELS, STATUS_NEW, STATUS_IN_PROGRESS, STATUS_COMPLETED

    user = await db.get_or_create_user_vk(**prof)
    reports = await db.get_reports_for_user(user["id"], limit=15)
    if not reports:
        return (
            "📊 *У тебя пока нет заявок.*\n\n"
            "Через *📍 Сообщить* отправь фото — они появятся здесь и на карте сайта."
        )

    total = len(reports)
    new_n = sum(1 for r in reports if r["status"] == STATUS_NEW)
    in_pr = sum(1 for r in reports if r["status"] == STATUS_IN_PROGRESS)
    done_n = sum(1 for r in reports if r["status"] == STATUS_COMPLETED)

    lines = [
        f"📊 *Твои заявки*: {total} (новые: {new_n}, в работе: {in_pr}, завершено: {done_n})",
        "",
    ]
    for r in reports:
        lbl = STATUS_LABELS.get(r["status"], r["status"])
        created = (
            str(r["created_at"])[:16].replace("T", " ")
            if r.get("created_at")
            else ""
        )
        lines.append(f"📋 №{r['id']} • {lbl} • {created} • 📎×{int(r.get('files_count') or 0)}")
    return "\n".join(lines)


async def process_event(vk, message: dict, media_dir: str) -> None:
    peer_id = message["peer_id"]
    from_id = int(message["from_id"])
    text_raw = message.get("text") or ""
    text = _norm(text_raw)
    attachments = message.get("attachments") or []
    geo = message.get("geo")

    prof = load_vk_user_profile(vk, from_id)

    def send(msg: str, keyboard: str | None = None) -> None:
        vk.messages.send(
            peer_id=peer_id,
            message=msg,
            keyboard=keyboard,
            random_id=get_random_id(),
        )

    start_cmds = {"/start", "старт", "привет", "начать"}
    reset_back = {"⬅️ назад", "назад"}

    if text in start_cmds:
        STATES.pop(from_id, None)
        send(WELCOME_TEXT, create_main_keyboard())
        return

    if text in reset_back:
        STATES.pop(from_id, None)
        send("Выбери действие:", create_main_keyboard())
        return

    if text in {"ℹ️ информация", "информация"}:
        STATES.pop(from_id, None)
        send(INFO_TEXT, create_back_keyboard())
        return

    if text in {"📊 мои заявки", "мои заявки"}:
        STATES.pop(from_id, None)
        body = await compose_my_reports(prof)
        send(body, create_back_keyboard())
        return

    if text in {"📍 сообщить о граффити", "сообщить", "сообщить о граффити"}:
        STATES[from_id] = {"phase": "media", "photos": [], "vk_profile": prof.copy()}
        send(
            "📍 *Новая заявка*\n\n"
            "1) Одно или несколько *фото*\n"
            "2) *✅ Готово*\n"
            "3) *Геолокация* 📎 или *адрес* текстом\n"
            "4) Комментарий или *Пропустить*\n\n"
            "По текстовому адресу координаты ищутся через OpenStreetMap (приоритет — Казань).",
            create_media_keyboard(),
        )
        return

    state = STATES.get(from_id)

    if state and state["phase"] == "media":
        got_photo = False
        for att in attachments:
            if att.get("type") != "photo":
                continue
            p = att.get("photo") or {}
            url = largest_photo_url(p)
            if not url:
                continue
            fname = f"vk_{from_id}_{uuid.uuid4().hex}.jpg"
            dest = os.path.join(media_dir, fname)
            try:
                download_url_to_file(url, dest)
                state["photos"].append(
                    {"file_path": fname, "file_id": str(p.get("id") or p.get("owner_id") or fname)}
                )
                got_photo = True
            except Exception as exc:
                send(f"❌ Не удалось сохранить фото: {exc}", create_media_keyboard())

        if got_photo:
            send(
                f"✅ Фото сохранено (всего: {len(state['photos'])}). Добавь ещё или *✅ Готово*.",
                create_media_keyboard(),
            )
            return

        if text == "✅ готово":
            if not state["photos"]:
                send("❌ Нужно хотя бы одно фото.", create_media_keyboard())
                return
            state["phase"] = "address"
            send(
                "📍 Пришли *геолокацию* или напиши *адрес*: улица, дом или ориентир.",
                create_back_keyboard(),
            )
            return

        send("📷 Отправь фото или *⬅️ Назад*.", create_media_keyboard())
        return

    if state and state["phase"] == "address":
        coords = vk_geo_lat_lon(geo)
        if coords:
            state["latitude"], state["longitude"] = coords
            pl = geo.get("place") if geo else None
            if isinstance(pl, dict) and pl.get("title"):
                state["address_text"] = pl["title"]
        elif text_raw.strip():
            geo_res = geocode_address_osm(text_raw.strip())
            if not geo_res:
                send(
                    "❌ Не удалось найти адрес на карте. Уточни формулировку или отправь точку 📎.",
                    create_back_keyboard(),
                )
                return
            lat, lon, disp = geo_res
            state["latitude"], state["longitude"] = lat, lon
            state["address_text"] = disp or text_raw.strip()
        else:
            send("Нужна *геолокация* 📎 или *текстовый адрес*.", create_back_keyboard())
            return

        state["phase"] = "description"
        state["vk_profile"] = prof.copy()
        send(
            f"✅ Место: *{state['latitude']:.5f}, {state['longitude']:.5f}*\n\n"
            "Комментарий к заявке (*⏭️ Пропустить*):",
            create_desc_keyboard(),
        )
        return

    if state and state["phase"] == "description":
        desc: str | None
        if text in {"⏭️ пропустить", "пропустить"}:
            desc = None
        else:
            desc = text_raw.strip() if text_raw.strip() else None

        state["vk_profile"] = prof.copy()
        rid = await finalize_report(state, desc)
        STATES.pop(from_id, None)

        from config import get_public_site_origin

        map_link = f"{get_public_site_origin()}/public-map"
        send(
            f"✅ *Заявка создана — №{rid}*\n\n"
            f"Карта (публично): {map_link}\n\n"
            "Спасибо за помощь 💪",
            create_main_keyboard(),
        )
        return

    if attachments:
        send(
            "Сначала меню → *📍 Сообщить о граффити*, потом отправляй материалы по шагам.",
            create_main_keyboard(),
        )
        return

    send("🤔 Выбери пункт меню или */start*", create_main_keyboard())


def main() -> None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import database as db
    from config import VK_TOKEN, VK_GROUP_ID, MEDIA_PATH

    os.makedirs(MEDIA_PATH, exist_ok=True)

    if not VK_TOKEN or not VK_GROUP_ID:
        print("⚠️  Задайте VK_TOKEN и VK_GROUP_ID (>0) в .env.")
        return

    asyncio.run(db.init_db())

    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    print("=" * 50)
    print("🎨  VK бот — учёт граффити, Казань")
    print("=" * 50)

    try:
        longpoll = VkBotLongPoll(vk_session, VK_GROUP_ID)
    except Exception as exc:
        print(f"❌ Long Poll: {exc}\nПроверьте токен сообщества и числовой id группы.")
        return

    print("🤖 VK бот в сети. Ctrl+C — выход\n")

    for event in longpoll.listen():
        if event.type != VkBotEventType.MESSAGE_NEW:
            continue
        msg = event.obj.message
        try:
            asyncio.run(process_event(vk, msg, MEDIA_PATH))
        except Exception as exc:
            print(f"[VK bot] {exc}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 VK бот остановлен")
