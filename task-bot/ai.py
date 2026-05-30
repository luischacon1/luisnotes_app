import json
import os
import openai

client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EXTRACTION_PROMPT = (
    "Dado este texto de voz, extrae en JSON: "
    '{"tarea": "...", "fecha_recordatorio": "YYYY-MM-DD HH:MM o null", "prioridad": "alta/media/baja"}. '
    "Si no hay fecha explícita, fecha_recordatorio es null. "
    "Si no hay prioridad explícita, asigna media. "
    "Responde solo con el JSON, sin texto adicional."
)


async def transcribe_audio(audio_path: str) -> str:
    with open(audio_path, "rb") as f:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="es",
        )
    return transcript.text


async def extract_task(text: str) -> dict:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content.strip()
    data = json.loads(raw)
    # Normalise fields
    if data.get("fecha_recordatorio") in ("null", "", "None"):
        data["fecha_recordatorio"] = None
    if data.get("prioridad") not in ("alta", "media", "baja"):
        data["prioridad"] = "media"
    return data


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
