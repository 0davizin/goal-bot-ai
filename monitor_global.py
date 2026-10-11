"""GOAL BOT AI - Monitor global ESPN (somente coleta; sem sinais Telegram).

Uso:
    python monitor_global.py --uma-vez
    python monitor_global.py
    python monitor_global.py --intervalo 180

Fonte ESPN nao oficial. A disponibilidade e a qualidade dos dados podem variar.
"""

import os
import argparse
import logging
import sqlite3
import time
from pathlib import Path

from api.espn import fetch_matches
from database.espn_storage import salvar_observacoes
from goalbot_gols import coletar as coletar_gols

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('GOALBOT_DB_PATH') or (Path(__file__).resolve().parent / 'goalbot.db' if Path(__file__).parent.name == 'database' else Path(__file__).resolve().parents[1] / 'database' / 'goalbot.db' if Path(__file__).parent.name in ('api','analysis') else Path(__file__).resolve().parent / 'database' / 'goalbot.db'))
LOG_DIR = ROOT / "logs"
LIVE_STATUSES = {"STATUS_FIRST_HALF", "STATUS_SECOND_HALF"}
CLOSING_STATUSES = {"STATUS_HALFTIME", "STATUS_FULL_TIME"}
REQUIRED = ("totalShots", "shotsOnTarget", "wonCorners")


def as_nonnegative_int(value):
    """Converte somente inteiros nao negativos; ausente/invalido => None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def ready_match(game):
    """Somente jogos em andamento, com dados basicos validos para ambos os times."""
    if game.get("status") not in LIVE_STATUSES:
        return False
    if not game.get("id") or not game.get("league_id") or not game.get("minute"):
        return False
    for side in ("home", "away"):
        team = game.get(side)
        if not isinstance(team, dict) or as_nonnegative_int(team.get("score")) is None:
            return False
        stats = team.get("statistics")
        if not isinstance(stats, dict):
            return False
        if any(as_nonnegative_int(stats.get(key)) is None for key in REQUIRED):
            return False
        if as_nonnegative_int(stats["shotsOnTarget"]) > as_nonnegative_int(stats["totalShots"]):
            return False
    return True


def signature_from_game(game):
    home, away = game["home"], game["away"]
    hs, aws = home["statistics"], away["statistics"]
    return (
        str(game["league_id"]), str(game["minute"]), str(game["status"]),
        str(as_nonnegative_int(home["score"])), str(as_nonnegative_int(away["score"])),
        as_nonnegative_int(hs["totalShots"]), as_nonnegative_int(aws["totalShots"]),
        as_nonnegative_int(hs["shotsOnTarget"]), as_nonnegative_int(aws["shotsOnTarget"]),
        as_nonnegative_int(hs["wonCorners"]), as_nonnegative_int(aws["wonCorners"]),
    )


def previous_signatures():
    """Ultima observacao de cada jogo, se a tabela ja existir."""
    if not DB.exists():
        return {}
    with sqlite3.connect(DB, timeout=15) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='observacoes_live'"
        ).fetchone()
        if not exists:
            return {}
        rows = conn.execute("""
            SELECT o.id_evento, o.liga, o.minuto, o.status,
                   o.placar_casa, o.placar_fora,
                   o.finalizacoes_casa, o.finalizacoes_fora,
                   o.chutes_gol_casa, o.chutes_gol_fora,
                   o.escanteios_casa, o.escanteios_fora
            FROM observacoes_live AS o
            INNER JOIN (
                SELECT id_evento, MAX(id) AS last_id
                FROM observacoes_live GROUP BY id_evento
            ) AS latest ON latest.last_id = o.id
        """).fetchall()
    return {str(row[0]): tuple(str(x) if i < 5 else x for i, x in enumerate(row[1:]))
            for row in rows}


def run_once():
    games = fetch_matches(league="all", limit=500)
    live = [g for g in games if g.get("status") in LIVE_STATUSES]
    valid = [g for g in live if ready_match(g)]
    prior = previous_signatures()
    changed = [g for g in valid if prior.get(str(g["id"])) != signature_from_game(g)]
    # Encerramentos SOMENTE de eventos que ja possuem observacoes ou sinais.
    # Nunca entram no filtro de oportunidades do monitor inteligente.
    acompanhados = set(prior)
    if DB.exists():
        with sqlite3.connect(DB, timeout=15) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sinais_telegram'").fetchone():
                acompanhados.update(str(r[0]) for r in conn.execute(
                    "SELECT id_evento FROM sinais_telegram WHERE status='PENDENTE'"))
    encerramentos = []
    for g in games:
        if g.get('status') not in CLOSING_STATUSES:
            continue
        # Registrar placar de intervalo de TODOS os jogos da ESPN, mesmo sem sinal.
        # Para FT manter o comportamento anterior, evitando carga excessiva.
        if g.get('status') == 'STATUS_FULL_TIME' and str(g.get('id')) not in acompanhados:
            continue
        casa, fora = g.get('home') or {}, g.get('away') or {}
        if (not g.get('id') or
            as_nonnegative_int(casa.get('score')) is None or
            as_nonnegative_int(fora.get('score')) is None):
            continue
        # So salvar transicao de status/placar; estatisticas de encerramento sao opcionais.
        old = prior.get(str(g['id']))
        if old and old[2] == g['status'] and old[3] == str(casa['score']) and old[4] == str(fora['score']):
            continue
        encerramentos.append(g)
    to_save = changed + encerramentos
    saved = salvar_observacoes(to_save, db_path=DB) if to_save else 0
    logging.info(
        "ESPN | total=%d | ao_vivo=%d | stats_validas=%d | novos_ou_alterados=%d | salvos=%d",
        len(games), len(live), len(valid), len(changed), saved,
    )
    logging.info("Encerramentos registrados=%d", len(encerramentos))
    try:
        coletar_gols(games, db=DB, max_consultas=12)
    except Exception:
        logging.exception("Falha isolada no historico de gols; motor de sinais preservado")
    logging.info("Telegram DESATIVADO. Nenhum sinal de aposta foi gerado.")
    return saved


def main():
    parser = argparse.ArgumentParser(description="GOAL BOT AI: monitor global ESPN sem sinais")
    parser.add_argument("--intervalo", type=int, default=120, help="Segundos entre rodadas (minimo 120)")
    parser.add_argument("--uma-vez", action="store_true", help="Coleta uma vez e encerra")
    args = parser.parse_args()
    if args.intervalo < 120:
        parser.error("Intervalo minimo: 120 segundos")

    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_DIR / "monitor_global.log", encoding="utf-8")],
    )
    logging.info("Monitor global iniciado | intervalo=%ds | sinais desativados", args.intervalo)
    try:
        while True:
            try:
                run_once()
            except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, RuntimeError) as exc:
                logging.exception("Falha na rodada: %s", exc)
            except Exception as exc:
                # Erros da biblioteca requests (incluindo timeout) nao encerram o loop.
                logging.exception("Falha inesperada na coleta: %s", exc)
            if args.uma_vez:
                break
            logging.info("Proxima consulta em %d segundos", args.intervalo)
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        logging.info("Monitor encerrado pelo usuario")


if __name__ == "__main__":
    main()
