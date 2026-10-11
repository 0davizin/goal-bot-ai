"""GOAL BOT AI: monitor de coleta, sem emissão de sinais."""
import argparse
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'database' / 'goalbot.db'
LOG_DIR = ROOT / 'logs'


def snapshot():
    with sqlite3.connect(DB, timeout=10) as conn:
        return {
            row[0]: (row[1], row[2], row[3], row[4], row[5])
            for row in conn.execute(
                'SELECT id_evento, mandante, visitante, status, gols_mandante, gols_visitante FROM coleta_eventos'
            )
        }


def run_once():
    before = snapshot()
    proc = subprocess.run(
        [sys.executable, '-m', 'api.football'],
        cwd=ROOT, capture_output=True, text=True, timeout=45,
    )
    if proc.returncode:
        logging.error('Falha na coleta (codigo %s): %s', proc.returncode, (proc.stderr or proc.stdout).strip()[-1000:])
        return False
    after = snapshot()
    logging.info('Coleta concluida | eventos armazenados: %d', len(after))
    for event_id, current in after.items():
        previous = before.get(event_id)
        if previous is None:
            logging.info('Novo evento: %s | %s x %s | status %s', event_id, *current[:3])
        elif previous[2:] != current[2:]:
            logging.info('Mudanca: %s | %s x %s | %s %s-%s -> %s %s-%s', event_id,
                         current[0], current[1], *previous[2:], *current[2:])
    return True


def main():
    parser = argparse.ArgumentParser(description='Monitor GOAL BOT AI - apenas coleta')
    parser.add_argument('--intervalo', type=int, default=180, help='Segundos entre coletas (minimo 120)')
    parser.add_argument('--uma-vez', action='store_true', help='Executar uma coleta e sair')
    args = parser.parse_args()
    if args.intervalo < 120:
        parser.error('O intervalo minimo e de 120 segundos')
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / 'monitor.log', encoding='utf-8')])
    logging.info('GOAL BOT AI | Monitor iniciado | sinais Telegram DESATIVADOS')
    try:
        while True:
            try:
                run_once()
            except (sqlite3.Error, subprocess.TimeoutExpired, OSError, ValueError) as exc:
                logging.error('Erro na rodada de coleta: %s', exc)
            if args.uma_vez:
                break
            logging.info('Proxima consulta em %d segundos', args.intervalo)
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        logging.info('Monitor encerrado pelo usuario')


if __name__ == '__main__':
    main()
