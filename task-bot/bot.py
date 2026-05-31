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

# Conversation history per user (in-memory, resets on bot restart)
_chat_histories: dict[int, list] = {}


def _task_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Hecho", callback_data=f"done_{task_id}"),
        InlineKeyboardButton("⏰ Posponer 1h", callback_data=f"postpone_{task_id}"),
        InlineKeyboardButton("🗑️ Eliminar", callback_data=f"delete_{task_id}"),
    ]])


async def _is_authorized(update: Update) -> bool:
    return update.effective_user.id == MY_TELEGRAM_ID


# ── Commands ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    await update.message.reply_text(
        "👋 Hola Luis, soy tu asistente personal.\n\n"
        "Puedes hablarme con voz o texto — crear tareas, preguntarme cosas, "
        "o decirme cómo quieres que me comporte.\n\n"
        "Comandos:\n"
        "/tareas — ver pendientes\n"
        "/completadas — ver completadas hoy\n"
        "/instrucciones — ver mis reglas actuales\n"
        "/reset — reiniciar conversación"
    )


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    tasks = database.get_pending_tasks()
    if not tasks:
        await update.message.reply_text("✨ No tienes tareas pendientes.")
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
    lines = ["✅ *Completadas hoy:*\n"] + [f"✔️ {t['descripcion']}" for t in tasks]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def show_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    content = ai.load_instructions()
    await update.message.reply_text(f"📋 *Instrucciones actuales:*\n\n{content}", parse_mode="Markdown")


async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    _chat_histories.pop(update.effective_user.id, None)
    await update.message.reply_text("🔄 Conversación reiniciada.")


# ── Message handlers ──────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    msg = await update.message.reply_text("🎙️ Transcribiendo...")
    voice = update.message.voice or update.message.audio
    tg_file = await context.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await tg_file.download_to_drive(tmp_path)
        transcript = await ai.transcribe_audio(tmp_path)
        await msg.edit_text(f"🎙️ _{transcript}_\n\n⏳ Pensando...", parse_mode="Markdown")
        await _assistant_reply(update, msg, transcript)
    finally:
        os.unlink(tmp_path)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    msg = await update.message.reply_text("⏳ Pensando...")
    await _assistant_reply(update, msg, update.message.text)


async def _assistant_reply(update: Update, msg, user_text: str) -> None:
    user_id = update.effective_user.id
    history = _chat_histories.get(user_id, [])

    try:
        response_text, new_history, meta = await ai.chat_with_assistant(user_text, history)
        _chat_histories[user_id] = new_history
        keyboard = _task_keyboard(meta["created_task_id"]) if meta.get("created_task_id") else None
        await msg.edit_text(response_text or "...", reply_markup=keyboard)
    except Exception as exc:
        logger.exception("Error en _assistant_reply: %s", exc)
        await msg.edit_text(f"❌ Error: {exc}")


# ── Inline button callbacks ───────────────────────────────────────────────────

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
        await query.edit_message_text(f"✅ Completada: {task['descripcion']}")

    elif action == "postpone":
        current = task["fecha_recordatorio"]
        base = datetime.now()
        if current:
            try:
                base = datetime.strptime(current, "%Y-%m-%d %H:%M")
            except ValueError:
                pass
        new_fecha = (base + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        database.update_fecha_recordatorio(task_id, new_fecha)
        await query.edit_message_text(
            f"⏰ Pospuesta: {task['descripcion']}\nNueva fecha: {new_fecha}",
            reply_markup=_task_keyboard(task_id),
        )

    elif action == "delete":
        database.delete_task(task_id)
        await query.edit_message_text(f"🗑️ Eliminada: {task['descripcion']}")


# ── App setup ─────────────────────────────────────────────────────────────────

def setup_bot(token: str) -> Application:
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tareas", list_tasks))
    app.add_handler(CommandHandler("completadas", list_completed))
    app.add_handler(CommandHandler("instrucciones", show_instructions))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app
