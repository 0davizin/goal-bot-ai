"""Persistência de observações ESPN em tabela independente."""
import os
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get('GOALBOT_DB_PATH') or (Path(__file__).resolve().parent / 'goalbot.db' if Path(__file__).parent.name == 'database' else Path(__file__).resolve().parents[1] / 'database' / 'goalbot.db' if Path(__file__).parent.name in ('api','analysis') else Path(__file__).resolve().parent / 'database' / 'goalbot.db'))


def salvar_observacoes(jogos, db_path=DB_PATH):
    """Insere um snapshot por partida; preserva os dados existentes."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS observacoes_live (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_evento TEXT NOT NULL,
            liga TEXT NOT NULL,
            minuto TEXT,
            status TEXT,
            placar_casa TEXT,
            placar_fora TEXT,
            finalizacoes_casa INTEGER,
            finalizacoes_fora INTEGER,
            chutes_gol_casa INTEGER,
            chutes_gol_fora INTEGER,
            escanteios_casa INTEGER,
            escanteios_fora INTEGER,
            coletado_em_utc TEXT NOT NULL,
            json_original TEXT NOT NULL
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_live_evento_tempo ON observacoes_live (id_evento, coletado_em_utc)')
        for jogo in jogos:
            casa = jogo.get('home') or {}
            fora = jogo.get('away') or {}
            ec = casa.get('statistics') or {}
            ef = fora.get('statistics') or {}
            def numero(v):
                try:
                    return int(v) if v is not None else None
                except (TypeError, ValueError):
                    return None
            con.execute('''INSERT INTO observacoes_live (
                id_evento, liga, minuto, status, placar_casa, placar_fora,
                finalizacoes_casa, finalizacoes_fora, chutes_gol_casa, chutes_gol_fora,
                escanteios_casa, escanteios_fora, coletado_em_utc, json_original
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                str(jogo['id']), jogo.get('league_id') or jogo.get('league',''), jogo.get('minute'), jogo.get('status'),
                casa.get('score'), fora.get('score'), numero(ec.get('totalShots')),
                numero(ef.get('totalShots')), numero(ec.get('shotsOnTarget')),
                numero(ef.get('shotsOnTarget')), numero(ec.get('wonCorners')),
                numero(ef.get('wonCorners')), jogo['collected_at_utc'],
                json.dumps(jogo, ensure_ascii=False),
            ))
    return len(jogos)
