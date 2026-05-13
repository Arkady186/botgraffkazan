"""Уведомления подателю заявки при смене статуса или комментарии оператора."""
from __future__ import annotations

import logging
import random
from typing import Optional

import aiohttp
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

import database as db
from config import BOT_TOKEN, VK_TOKEN, STATUS_LABELS

logger = logging.getLogger(__name__)


def _format_message(report_id: int, new_status: str, comment: Optional[str]) -> str:
    label = STATUS_LABELS.get(new_status, new_status)
    lines = [f"📋 Заявка #{report_id}", f"Статус: {label}"]
    c = (comment or "").strip()
    if c:
        lines.append(f"💬 Комментарий: {c}")
    return "\n".join(lines)


async def notify_submitter_status_update(
    report_id: int,
    old_status: Optional[str],
    new_status: str,
    comment: Optional[str] = None,
) -> None:
    """Отправить уведомление автору (Telegram или VK), если не аноним и не заявка с сайта без пользователя."""
    report = await db.get_report(report_id)
    if not report:
        return
    uid = report.get("user_id")
    if uid is None or uid == 0:
        return
    if report.get("is_anonymous"):
        return

    tid = report.get("telegram_id")
    if tid is None:
        return

    has_comment = bool((comment or "").strip())
    status_changed = old_status != new_status
    if not status_changed and not has_comment:
        return

    text = _format_message(report_id, new_status, comment)

    try:
        if tid > 0:
            if not BOT_TOKEN:
                return
            bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties())
            try:
                await bot.send_message(chat_id=tid, text=text)
            finally:
                await bot.session.close()
        else:
            if not VK_TOKEN:
                return
            vk_uid = abs(int(tid))
            params = {
                "user_id": vk_uid,
                "message": text,
                "random_id": random.randint(1, 2_147_483_647),
                "access_token": VK_TOKEN,
                "v": "5.199",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.vk.com/method/messages.send", params=params
                ) as resp:
                    data = await resp.json()
                    err = data.get("error")
                    if err:
                        logger.warning("VK messages.send error: %s", err)
    except Exception:
        logger.exception("notify_submitter_status_update failed report_id=%s", report_id)
