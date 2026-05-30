# Task Bot — Gestión de Tareas por Voz en Telegram

Bot personal de Telegram para gestionar tareas enviando mensajes de voz o texto. Transcribe audios con Whisper, extrae tareas con GPT-4o-mini y programa recordatorios automáticos.

## Funcionalidades

- **Voz → Tarea**: envía un audio y el bot lo transcribe, extrae la tarea, fecha y prioridad automáticamente
- **Texto → Tarea**: también acepta texto plano
- **Botones inline**: ✅ Hecho · ⏰ Posponer 1h · 🗑️ Eliminar
- **Recordatorios**: si dices "recuérdame X el día Y a las Z", te notifica a esa hora
- **Resumen matutino** (08:30): lista de tareas pendientes ordenadas por prioridad
- **Resumen nocturno** (21:00): tareas completadas, pendientes y sugerencia GPT de qué priorizar
- **Comandos**: `/tareas` y `/completadas`

## Instalación local

### 1. Clonar el repositorio

```bash
git clone https://github.com/luischacon1/luisnotes_app.git
cd luisnotes_app/task-bot
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con tus valores:

```
TELEGRAM_TOKEN=<token de @BotFather>
OPENAI_API_KEY=<tu API key de OpenAI>
MY_TELEGRAM_ID=<tu ID numérico de Telegram>
```

> Para obtener tu ID de Telegram habla con [@userinfobot](https://t.me/userinfobot).

### 4. Ejecutar

```bash
python main.py
```

---

## Despliegue en Railway

### Paso 1 — Preparar el repositorio

Asegúrate de que el código está en GitHub (push a `main`):

```bash
git add .
git commit -m "feat: task bot initial setup"
git push origin main
```

### Paso 2 — Crear proyecto en Railway

1. Entra en [railway.app](https://railway.app) e inicia sesión con GitHub.
2. Pulsa **New Project → Deploy from GitHub repo**.
3. Selecciona `luischacon1/luisnotes_app`.

### Paso 3 — Configurar el directorio raíz

En el panel del servicio ve a **Settings → Source**:

- **Root Directory**: `task-bot`

Railway instalará las dependencias de `requirements.txt` desde esa carpeta.

### Paso 4 — Configurar variables de entorno

En el panel del servicio ve a **Variables** y añade:

| Variable | Valor |
|---|---|
| `TELEGRAM_TOKEN` | Token de @BotFather |
| `OPENAI_API_KEY` | Tu API key de OpenAI |
| `MY_TELEGRAM_ID` | Tu ID numérico de Telegram |

### Paso 5 — Configurar el comando de arranque

Railway leerá el `Procfile` automáticamente. El proceso es de tipo `worker` (no necesita puerto HTTP).

Si Railway no detecta el Procfile, ve a **Settings → Deploy → Start Command** y escribe:

```
python main.py
```

### Paso 6 — Deploy

Pulsa **Deploy** (o haz un nuevo push a `main`). Railway arrancará el bot. Puedes ver los logs en la pestaña **Logs** del servicio.

### Paso 7 — Verificar

Manda `/start` a tu bot en Telegram. Deberías recibir el mensaje de bienvenida.

---

## Estructura del proyecto

```
task-bot/
├── main.py          # Punto de entrada: inicializa DB, bot y scheduler
├── bot.py           # Handlers de Telegram (voz, texto, callbacks)
├── ai.py            # Whisper (transcripción) + GPT-4o-mini (extracción/resúmenes)
├── database.py      # CRUD sobre SQLite (tasks.db)
├── scheduler.py     # APScheduler: recordatorios, resumen mañana y noche
├── requirements.txt
├── Procfile
├── .env.example
└── README.md
```

## Zona horaria

El scheduler usa `Europe/Madrid` por defecto. Para cambiarla edita la línea en `scheduler.py`:

```python
scheduler = AsyncIOScheduler(timezone="America/Mexico_City")
```
