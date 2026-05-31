import sqlite3
import os
from datetime import datetime
from zoneinfo import ZoneInfo

MADRID_TZ = ZoneInfo("Europe/Madrid")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                descripcion TEXT NOT NULL,
                fecha_recordatorio TEXT,
                prioridad TEXT DEFAULT 'media',
                completada INTEGER DEFAULT 0,
                fecha_creacion TEXT DEFAULT (datetime('now')),
                fecha_completada TEXT
            )
        """)
        conn.commit()


def add_task(descripcion: str, fecha_recordatorio: str = None, prioridad: str = "media") -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO tasks (descripcion, fecha_recordatorio, prioridad) VALUES (?, ?, ?)",
            (descripcion, fecha_recordatorio, prioridad),
        )
        conn.commit()
        return cursor.lastrowid


def get_task(task_id: int):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def get_pending_tasks():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM tasks
            WHERE completada = 0
            ORDER BY
                CASE prioridad
                    WHEN 'alta'  THEN 1
                    WHEN 'media' THEN 2
                    WHEN 'baja'  THEN 3
                    ELSE 4
                END,
                fecha_creacion
            """
        ).fetchall()


def get_completed_today():
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM tasks WHERE completada = 1 AND DATE(fecha_completada) = DATE('now')"
        ).fetchall()


def mark_completed(task_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET completada = 1, fecha_completada = ? WHERE id = ?",
            (datetime.now(MADRID_TZ).strftime("%Y-%m-%d %H:%M:%S"), task_id),
        )
        conn.commit()


def delete_task(task_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()


def update_fecha_recordatorio(task_id: int, nueva_fecha: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET fecha_recordatorio = ? WHERE id = ?",
            (nueva_fecha, task_id),
        )
        conn.commit()


def find_tasks_by_description(query: str):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM tasks WHERE completada = 0 AND descripcion LIKE ? ORDER BY fecha_creacion DESC",
            (f"%{query}%",),
        ).fetchall()


def get_due_reminders():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM tasks
            WHERE completada = 0
              AND fecha_recordatorio IS NOT NULL
              AND fecha_recordatorio <= ?
            """,
            (now,),
        ).fetchall()
