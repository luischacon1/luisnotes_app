import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import openai

client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MADRID_TZ = ZoneInfo("Europe/Madrid")
INSTRUCTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instructions.md")

_BASE_SYSTEM = """Eres el asistente personal de Luis. Gestionas su lista de tareas pero también \
puedes responder preguntas, dar consejos y mantener conversación natural.

Cuando el usuario te pida cambiar tu comportamiento o diga "de ahora en adelante X", \
usa save_instructions para actualizar tus propias reglas escribiendo el contenido COMPLETO actualizado.

Fecha y hora actual (Madrid): {now}
Zona horaria: Europe/Madrid. Todas las fechas y horas que interpretes o generes deben ser en hora de Madrid.

## Instrucciones personalizadas:
{instructions}"""


def load_instructions() -> str:
    if os.path.exists(INSTRUCTIONS_PATH):
        with open(INSTRUCTIONS_PATH, encoding="utf-8") as f:
            return f.read()
    return "Sin instrucciones personalizadas aún."


def _write_instructions(content: str) -> None:
    with open(INSTRUCTIONS_PATH, "w", encoding="utf-8") as f:
        f.write(content)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Crea una nueva tarea o recordatorio en la lista del usuario",
            "parameters": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string", "description": "Descripción clara de la tarea"},
                    "fecha_recordatorio": {
                        "type": "string",
                        "description": "Fecha y hora exacta en formato YYYY-MM-DD HH:MM, o null"
                    },
                    "prioridad": {
                        "type": "string",
                        "enum": ["alta", "media", "baja"]
                    }
                },
                "required": ["descripcion", "prioridad"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending_tasks",
            "description": "Obtiene las tareas pendientes ordenadas por prioridad",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_completed_tasks",
            "description": "Obtiene las tareas completadas hoy",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mark_task_done",
            "description": "Marca una tarea como completada buscándola por nombre aproximado",
            "parameters": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string", "description": "Parte del nombre de la tarea"}
                },
                "required": ["descripcion"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Elimina permanentemente una tarea buscándola por nombre aproximado",
            "parameters": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string"}
                },
                "required": ["descripcion"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "postpone_task",
            "description": "Pospone una tarea a una nueva fecha y hora",
            "parameters": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string", "description": "Parte del nombre de la tarea"},
                    "nueva_fecha": {"type": "string", "description": "Nueva fecha en formato YYYY-MM-DD HH:MM"}
                },
                "required": ["descripcion", "nueva_fecha"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_instructions",
            "description": (
                "Actualiza las instrucciones personalizadas del asistente. "
                "Úsalo cuando el usuario pida cambiar comportamiento, añadir reglas o diga "
                "'de ahora en adelante X'. Escribe el contenido COMPLETO y actualizado en markdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Contenido completo actualizado del archivo de instrucciones (markdown)"
                    }
                },
                "required": ["content"]
            }
        }
    }
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


async def chat_with_assistant(user_message: str, history: list) -> tuple[str, list, dict]:
    """
    Returns (response_text, updated_history, meta).
    meta = {"created_task_id": int | None}
    """
    import database

    system = _BASE_SYSTEM.format(
        now=datetime.now(MADRID_TZ).strftime("%Y-%m-%d %H:%M (%A)"),
        instructions=load_instructions(),
    )
    messages: list = [{"role": "system", "content": system}] + history + [
        {"role": "user", "content": user_message}
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
        messages.append(_msg_to_dict(msg))

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            result = await _execute_tool(
                tc.function.name, json.loads(tc.function.arguments), meta
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    # Keep last 30 messages (exclude system)
    new_history = messages[1:]
    if len(new_history) > 30:
        new_history = new_history[-30:]

    return msg.content or "", new_history, meta


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
        rows = database.get_pending_tasks()
        return {"tasks": [dict(r) for r in rows]}

    if name == "list_completed_tasks":
        rows = database.get_completed_today()
        return {"tasks": [dict(r) for r in rows]}

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

    if name == "save_instructions":
        _write_instructions(args["content"])
        return {"ok": True}

    return {"error": f"Herramienta desconocida: {name}"}


async def transcribe_audio(audio_path: str) -> str:
    with open(audio_path, "rb") as f:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="es",
        )
    return transcript.text


async def generate_evening_summary(completed: list, pending: list) -> str:
    completed_str = "\n".join(f"- {t['descripcion']}" for t in completed) or "Ninguna"
    pending_str = (
        "\n".join(f"- [{t['prioridad']}] {t['descripcion']}" for t in pending) or "Ninguna"
    )
    prompt = (
        "Eres un asistente de productividad personal. Genera un resumen nocturno breve y motivador.\n\n"
        f"Tareas completadas hoy:\n{completed_str}\n\n"
        f"Tareas pendientes:\n{pending_str}\n\n"
        "Incluye: resumen del día, estado de tareas pendientes, y sugerencia concreta de qué priorizar mañana. "
        "Sé breve, directo y positivo. Responde en español."
    )
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()
