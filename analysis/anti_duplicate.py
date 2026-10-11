import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "database" / "goalbot.db"


def preparar():
    with sqlite3.connect(DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS alertas_enviados (
                id_evento TEXT NOT NULL,
                periodo TEXT NOT NULL,
                enviado_em TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id_evento, periodo)
            )
        """)


def ja_enviado(evento, periodo):
    preparar()

    with sqlite3.connect(DB) as con:
        registro = con.execute(
            """
            SELECT 1 FROM alertas_enviados
            WHERE id_evento = ? AND periodo = ?
            """,
            (str(evento), str(periodo))
        ).fetchone()

    return registro is not None


def registrar_envio(evento, periodo):
    preparar()

    with sqlite3.connect(DB) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO alertas_enviados
            (id_evento, periodo)
            VALUES (?, ?)
            """,
            (str(evento), str(periodo))
        )
