import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import openai

client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MADRID_TZ = ZoneInfo("Europe/Madrid")

_SYSTEM = """Eres la asistente personal de Luis. No eres un chatbot genérico — eres alguien que le conoce, \
recuerda lo que ha dicho antes y le ayuda a tomar mejores decisiones sobre su tiempo y prioridades.

Actúa como una persona real de confianza: sé cercana, directa y proactiva. \
Si ves que tiene demasiadas cosas urgentes, díselo. Si algo lleva mucho tiempo pendiente, menciónalo. \
Si puede agrupar tareas o hay un mejor momento para hacerlas, sugiérelo. \
No esperes a que te pregunte — anticípate.

Cuando aprendas algo importante sobre Luis (rutinas, preferencias, personas clave, compromisos recurrentes), \
guárdalo en memoria usando save_memory para recordarlo en el futuro.

Cuando Luis te pida cambiar tu comportamiento o diga "de ahora en adelante X", \
usa save_instructions para actualizar tus propias reglas.

Fecha y hora actual (Madrid): {now}
Zona horaria: Europe/Madrid — interpreta y genera siempre las horas en hora de Madrid.

## Lo que sé de Luis:
{memory}

## Mis instrucciones personalizadas:
{instructions}"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Crea una nueva tarea o recordatorio",
            "parameters": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string"},
                    "fecha_recordatorio": {"type": "string", "description": "YYYY-MM-DD HH:MM o null"},
                    "prioridad": {"type": "string", "enum": ["alta", "media", "baja"]},
                },
                "required": ["descripcion", "prioridad"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending_tasks",
            "description": "Obtiene las tareas pendientes ordenadas por prioridad",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_completed_tasks",
            "description": "Obtiene las tareas completadas hoy",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_task_done",
            "description": "Marca una tarea como completada buscándola por nombre aproximado",
            "parameters": {
                "type": "object",
                "properties": {"descripcion": {"type": "string"}},
                "required": ["descripcion"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Elimina una tarea buscándola por nombre aproximado",
            "parameters": {
                "type": "object",
                "properties": {"descripcion": {"type": "string"}},
                "required": ["descripcion"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "postpone_task",
            "description": "Pospone una tarea a una nueva fecha y hora",
            "parameters": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string"},
                    "nueva_fecha": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                },
                "required": ["descripcion", "nueva_fecha"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Guarda información importante sobre Luis para recordarla en conversaciones futuras: "
                "rutinas, preferencias, personas clave, compromisos recurrentes, contexto personal. "
                "Escribe el contenido COMPLETO y actualizado en markdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_instructions",
            "description": (
                "Actualiza las instrucciones de comportamiento del asistente. "
                "Úsalo cuando Luis pida cambiar cómo te comportas o diga 'de ahora en adelante X'. "
                "Escribe el contenido COMPLETO y actualizado en markdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        },
    },
]


def _msg_to_dict(msg) -> dict:
    d: dict = {"role": msg.role, "content": msg.content}
    if getattr(msg, "tool_calls", None):
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return d


async def chat_with_assistant(user_message: str) -> tuple[str, dict]:
    """Returns (response_text, meta).  meta = {'created_task_id': int | None}"""
    import database

    # Save the user's message immediately
    database.append_message("user", content=user_message)

    # Build messages: system + persisted history (already includes the user message just saved)
    history_rows = database.get_conversation_history(limit=60)
    system = _SYSTEM.format(
        now=datetime.now(MADRID_TZ).strftime("%Y-%m-%d %H:%M (%A)"),
        memory=database.get_memory(),
        instructions=database.get_instructions(),
    )
    messages: list = [{"role": "system", "content": system}] + [
        database.row_to_message(r) for r in history_rows
    ]

    meta: dict = {"created_task_id": None}

    while True:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        # Persist assistant turn
        tool_calls_data = None
        if msg.tool_calls:
            tool_calls_data = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        database.append_message("assistant", content=msg.content, tool_calls=tool_calls_data)
        messages.append(_msg_to_dict(msg))

        if not msg.tool_calls:
            break

        # Execute tools and persist results
        for tc in msg.tool_calls:
            result = await _execute_tool(tc.function.name, json.loads(tc.function.arguments), meta)
            result_str = json.dumps(result, ensure_ascii=False)
            database.append_message("tool", content=result_str, tool_call_id=tc.id)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

    return msg.content or "", meta


async def _execute_tool(name: str, args: dict, meta: dict) -> dict:
    import database

    if name == "create_task":
        task_id = database.add_task(
            args["descripcion"],
            args.get("fecha_recordatorio"),
            args.get("prioridad", "media"),
        )
        meta["created_task_id"] = task_id
        return {"ok": True, "task_id": task_id, "descripcion": args["descripcion"]}

    if name == "list_pending_tasks":
        return {"tasks": [dict(r) for r in database.get_pending_tasks()]}

    if name == "list_completed_tasks":
        return {"tasks": [dict(r) for r in database.get_completed_today()]}

    if name == "mark_task_done":
        matches = database.find_tasks_by_description(args["descripcion"])
        if not matches:
            return {"ok": False, "error": "No se encontró ninguna tarea con ese nombre"}
        database.mark_completed(matches[0]["id"])
        return {"ok": True, "descripcion": matches[0]["descripcion"]}

    if name == "delete_task":
        matches = database.find_tasks_by_description(args["descripcion"])
        if not matches:
            return {"ok": False, "error": "No se encontró ninguna tarea con ese nombre"}
        database.delete_task(matches[0]["id"])
        return {"ok": True, "descripcion": matches[0]["descripcion"]}

    if name == "postpone_task":
        matches = database.find_tasks_by_description(args["descripcion"])
        if not matches:
            return {"ok": False, "error": "No se encontró ninguna tarea con ese nombre"}
        database.update_fecha_recordatorio(matches[0]["id"], args["nueva_fecha"])
        return {"ok": True, "descripcion": matches[0]["descripcion"], "nueva_fecha": args["nueva_fecha"]}

    if name == "save_memory":
        database.save_memory(args["content"])
        return {"ok": True}

    if name == "save_instructions":
        database.save_instructions(args["content"])
        return {"ok": True}

    return {"error": f"Herramienta desconocida: {name}"}


async def transcribe_audio(audio_path: str) -> str:
    with open(audio_path, "rb") as f:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1", file=f, language="es"
        )
    return transcript.text


async def generate_evening_summary(completed: list, pending: list) -> str:
    completed_str = "\n".join(f"- {t['descripcion']}" for t in completed) or "Ninguna"
    pending_str = (
        "\n".join(f"- [{t['prioridad']}] {t['descripcion']}" for t in pending) or "Ninguna"
    )
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": (
                "Eres el asistente personal de Luis. Genera un resumen nocturno breve y motivador.\n\n"
                f"Tareas completadas hoy:\n{completed_str}\n\n"
                f"Tareas pendientes:\n{pending_str}\n\n"
                "Incluye: qué tal ha ido el día, estado de pendientes, y qué priorizar mañana. "
                "Breve, directo, positivo. En español."
            ),
        }],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()
