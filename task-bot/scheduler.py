import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import ai
import database

logger = logging.getLogger(__name__)

MY_TELEGRAM_ID = int(os.getenv("MY_TELEGRAM_ID", "0"))

PRIORITY_EMOJI = {"alta": "🔴", "media": "🟡", "baja": "🟢"}


def _task_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Hecho", callback_data=f"done_{task_id}"),
            InlineKeyboardButton("⏰ Posponer 1h", callback_data=f"postpone_{task_id}"),
            InlineKeyboardButton("🗑️ Eliminar", callback_data=f"delete_{task_id}"),
        ]
    ])


async def send_morning_summary(application) -> None:
    tasks = database.get_pending_tasks()
    if not tasks:
        text = "🌅 *Buenos días\\!* No tienes tareas pendientes\\. ¡Día libre\\! 🎉"
    else:
        lines = ["🌅 *Buenos días\\! Tus tareas pendientes:*\n"]
        for t in tasks:
            emoji = PRIORITY_EMOJI.get(t["prioridad"], "⚪")
            fecha = f"\n   _vence: {t['fecha_recordatorio']}_" if t["fecha_recordatorio"] else ""
            lines.append(f"{emoji} {t['descripcion']}{fecha}")
        text = "\n".join(lines)

    await application.bot.send_message(
        chat_id=MY_TELEGRAM_ID,
        text=text,
        parse_mode="MarkdownV2",
    )


async def send_evening_summary(application) -> None:
    completed = [dict(t) for t in database.get_completed_today()]
    pending = [dict(t) for t in database.get_pending_tasks()]

    try:
        summary = await ai.generate_evening_summary(completed, pending)
    except Exception as exc:
        logger.error("Error generando resumen nocturno: %s", exc)
        summary = "No se pudo generar el resumen automático."

    lines = ["🌙 *Resumen nocturno*\n"]
    lines.append(f"✅ Completadas hoy: {len(completed)}")
    lines.append(f"📋 Pendientes: {len(pending)}\n")
    lines.append(summary)

    await application.bot.send_message(
        chat_id=MY_TELEGRAM_ID,
        text="\n".join(lines),
        parse_mode="Markdown",
    )


async def check_reminders(application) -> None:
    due = database.get_due_reminders()
    for task in due:
        text = (
            f"⏰ *Recordatorio\\!*\n\n"
            f"📌 {task['descripcion']}\n"
            f"Prioridad: *{task['prioridad']}*"
        )
        try:
            await application.bot.send_message(
                chat_id=MY_TELEGRAM_ID,
                text=text,
                reply_markup=_task_keyboard(task["id"]),
                parse_mode="MarkdownV2",
            )
        except Exception as exc:
            logger.error("Error enviando recordatorio tarea %s: %s", task["id"], exc)
        # Clear so it doesn't fire again
        database.update_fecha_recordatorio(task["id"], None)


def setup_scheduler(application) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Madrid")

    scheduler.add_job(
        send_morning_summary,
        CronTrigger(hour=8, minute=30),
        args=[application],
        id="morning_summary",
    )
    scheduler.add_job(
        send_evening_summary,
        CronTrigger(hour=21, minute=0),
        args=[application],
        id="evening_summary",
    )
    scheduler.add_job(
        check_reminders,
        "interval",
        minutes=1,
        args=[application],
        id="check_reminders",
    )

    return scheduler
