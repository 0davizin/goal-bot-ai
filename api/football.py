"""Coletor experimental TheSportsDB para GOAL BOT AI.

Não é uma fonte live validada para emissão de sinais.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://www.thesportsdb.com/api/v1/json/123"
DB_PATH = Path(__file__).resolve().parents[1] / "database" / "goalbot.db"
TZ = ZoneInfo("America/Sao_Paulo")


def fetch_events(day: str) -> list[dict]:
    response = requests.get(
        f"{BASE_URL}/eventsday.php",
        params={"d": day, "s": "Soccer"},
        timeout=20,
        headers={"User-Agent": "GOAL-BOT-AI/0.1 (experimental)"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Resposta da API em formato inesperado")
    events = payload.get("events") or []
    if not isinstance(events, list):
        raise ValueError("Campo 'events' inválido")
    return [event for event in events if isinstance(event, dict)]


def save_events(events: list[dict], fetched_at: str) -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    with sqlite3.connect(DB_PATH) as conn:
        # Tabela própria: preserva integralmente a tabela 'partidas' existente.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coleta_eventos (
                id_evento TEXT PRIMARY KEY,
                mandante TEXT NOT NULL,
                visitante TEXT NOT NULL,
                liga TEXT,
                data_evento TEXT,
                status TEXT,
                gols_mandante INTEGER,
                gols_visitante INTEGER,
                coletado_em_utc TEXT NOT NULL,
                fonte TEXT NOT NULL,
                json_original TEXT NOT NULL
            )
        """)
        for event in events:
            event_id = event.get("idEvent")
            home = event.get("strHomeTeam")
            away = event.get("strAwayTeam")
            if not event_id or not home or not away:
                continue
            conn.execute("""
                INSERT INTO coleta_eventos (
                    id_evento, mandante, visitante, liga, data_evento,
                    status, gols_mandante, gols_visitante, coletado_em_utc,
                    fonte, json_original
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id_evento) DO UPDATE SET
                    mandante=excluded.mandante,
                    visitante=excluded.visitante,
                    liga=excluded.liga,
                    data_evento=excluded.data_evento,
                    status=excluded.status,
                    gols_mandante=excluded.gols_mandante,
                    gols_visitante=excluded.gols_visitante,
                    coletado_em_utc=excluded.coletado_em_utc,
                    json_original=excluded.json_original
            """, (
                str(event_id), home, away, event.get("strLeague"),
                event.get("dateEvent"), event.get("strStatus"),
                event.get("intHomeScore"), event.get("intAwayScore"),
                fetched_at, "TheSportsDB", json.dumps(event, ensure_ascii=False),
            ))
            saved += 1
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Coleta experimental de partidas")
    parser.add_argument("--date", help="Data YYYY-MM-DD; padrão: hoje em Brasília")
    args = parser.parse_args()
    day = args.date or datetime.now(TZ).date().isoformat()
    try:
        datetime.strptime(day, "%Y-%m-%d")
        events = fetch_events(day)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        saved = save_events(events, fetched_at)
    except (requests.RequestException, ValueError, sqlite3.Error) as exc:
        raise SystemExit(f"ERRO NA COLETA: {exc}") from exc
    print(f"GOAL BOT AI | Data: {day}")
    print(f"Eventos recebidos: {len(events)} | Registros salvos: {saved}")
    print(f"Banco: {DB_PATH}")
    for event in events:
        print(f"- {event.get('strEvent', 'Sem nome')} | {event.get('strStatus') or 'sem status'}")
    print("AVISO: dados live e estatísticas avançadas ainda não validados.")


if __name__ == "__main__":
    main()
