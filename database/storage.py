"""Persistência de partidas do GOAL BOT AI em SQLite."""
import os
from pathlib import Path
import sqlite3

DB_PATH = Path(os.environ.get('GOALBOT_DB_PATH') or (Path(__file__).resolve().parent / 'goalbot.db' if Path(__file__).parent.name == 'database' else Path(__file__).resolve().parents[1] / 'database' / 'goalbot.db' if Path(__file__).parent.name in ('api','analysis') else Path(__file__).resolve().parent / 'database' / 'goalbot.db'))


def conectar():
    """Abre uma conexão com o banco local."""
    return sqlite3.connect(DB_PATH)


def inicializar_banco():
    """Cria a tabela se ainda não existir; preserva dados anteriores."""
    with conectar() as conexao:
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS partidas (
                id TEXT PRIMARY KEY,
                mandante TEXT,
                visitante TEXT,
                status TEXT
            )
        """)


def salvar_partida(id_partida, mandante, visitante, status):
    """Insere ou atualiza uma partida pelo seu ID, sem duplicação."""
    if not str(id_partida).strip():
        raise ValueError("O ID da partida não pode ser vazio.")
    with conectar() as conexao:
        conexao.execute("""
            INSERT INTO partidas (id, mandante, visitante, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                mandante = excluded.mandante,
                visitante = excluded.visitante,
                status = excluded.status
        """, (str(id_partida), mandante, visitante, status))


def listar_partidas():
    """Retorna todas as partidas armazenadas."""
    with conectar() as conexao:
        return conexao.execute(
            "SELECT id, mandante, visitante, status FROM partidas ORDER BY id"
        ).fetchall()


if __name__ == "__main__":
    inicializar_banco()
    print("GOAL BOT AI - SQLite pronto!")
    print("Partidas cadastradas:", len(listar_partidas()))
