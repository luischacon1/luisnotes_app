import logging
import os
import tempfile
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

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


def _priority_line(prioridad: str) -> str:
    return f"{PRIORITY_EMOJI.get(prioridad, '⚪')} Prioridad: *{prioridad}*"


async def _is_authorized(update: Update) -> bool:
    return update.effective_user.id == MY_TELEGRAM_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    await update.message.reply_text(
        "👋 *Bot de Tareas Personal*\n\n"
        "Envíame un mensaje de voz o texto con una tarea.\n\n"
        "📌 *Comandos disponibles:*\n"
        "/tareas — Ver tareas pendientes\n"
        "/completadas — Ver tareas completadas hoy",
        parse_mode="Markdown",
    )


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    tasks = database.get_pending_tasks()
    if not tasks:
        await update.message.reply_text("✨ No tienes tareas pendientes. ¡Todo al día!")
        return
    lines = ["📋 *Tareas pendientes:*\n"]
    for t in tasks:
        emoji = PRIORITY_EMOJI.get(t["prioridad"], "⚪")
        fecha = f"\n   _📅 {t['fecha_recordatorio']}_" if t["fecha_recordatorio"] else ""
        lines.append(f"{emoji} *{t['id']}.* {t['descripcion']}{fecha}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def list_completed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    tasks = database.get_completed_today()
    if not tasks:
        await update.message.reply_text("Aún no has completado ninguna tarea hoy.")
        return
    lines = ["✅ *Tareas completadas hoy:*\n"]
    for t in tasks:
        lines.append(f"✔️ {t['descripcion']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    msg = await update.message.reply_text("🎙️ Transcribiendo audio...")

    voice = update.message.voice or update.message.audio
    tg_file = await context.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await tg_file.download_to_drive(tmp_path)
        transcript = await ai.transcribe_audio(tmp_path)
        await msg.edit_text(
            f"📝 _\"{transcript}\"_\n\n⏳ Extrayendo tarea...",
            parse_mode="Markdown",
        )
        extracted = await ai.extract_task(transcript)
        await _save_and_reply(msg, extracted)
    finally:
        os.unlink(tmp_path)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    text = update.message.text
    msg = await update.message.reply_text("⏳ Procesando tarea...")
    extracted = await ai.extract_task(text)
    await _save_and_reply(msg, extracted)


async def _save_and_reply(msg, extracted: dict) -> None:
    tarea = extracted.get("tarea") or "Sin descripción"
    fecha = extracted.get("fecha_recordatorio")
    prioridad = extracted.get("prioridad", "media")

    task_id = database.add_task(tarea, fecha, prioridad)
    emoji = PRIORITY_EMOJI.get(prioridad, "⚪")
    fecha_text = f"\n📅 Fecha: `{fecha}`" if fecha else ""

    text = (
        f"✅ *Tarea creada*\n\n"
        f"{emoji} {tarea}{fecha_text}\n"
        f"Prioridad: *{prioridad}*"
    )
    await msg.edit_text(text, reply_markup=_task_keyboard(task_id), parse_mode="Markdown")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action, task_id_str = query.data.rsplit("_", 1)
    task_id = int(task_id_str)

    task = database.get_task(task_id)
    if not task:
        await query.edit_message_text("⚠️ Tarea no encontrada.")
        return

    if action == "done":
        database.mark_completed(task_id)
        await query.edit_message_text(
            f"✅ *Completada:* {task['descripcion']}", parse_mode="Markdown"
        )

    elif action == "postpone":
        current = task["fecha_recordatorio"]
        if current:
            try:
                base = datetime.strptime(current, "%Y-%m-%d %H:%M")
            except ValueError:
                base = datetime.now()
        else:
            base = datetime.now()
        new_fecha = (base + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        database.update_fecha_recordatorio(task_id, new_fecha)
        await query.edit_message_text(
            f"⏰ *Pospuesta:* {task['descripcion']}\n📅 Nueva fecha: `{new_fecha}`",
            reply_markup=_task_keyboard(task_id),
            parse_mode="Markdown",
        )

    elif action == "delete":
        database.delete_task(task_id)
        await query.edit_message_text(
            f"🗑️ *Eliminada:* {task['descripcion']}", parse_mode="Markdown"
        )


def setup_bot(token: str) -> Application:
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tareas", list_tasks))
    app.add_handler(CommandHandler("completadas", list_completed))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app
