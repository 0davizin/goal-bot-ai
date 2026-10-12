"""GOAL BOT AI - coleta global e análise experimental (sem Telegram).

Preserva os módulos existentes. A análise não constitui sinal de aposta.
"""
import argparse
import os
import json
import sqlite3
from goalbot_resultados import inicializar, atualizar_pendentes, registrar_sinal, formatar_entrada
import logging
import sys
import time
from collections import Counter
from pathlib import Path




from analysis.anti_duplicate import ja_enviado, registrar_envio
from telegram.notifier import enviar_mensagem, editar_mensagem, iniciar_comandos
from monitor_global import run_once

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('GOALBOT_DB_PATH') or ROOT / 'database' / 'goalbot.db')


def rodada(limite: int) -> None:
    import sqlite3

    logging.info("Iniciando coleta global ESPN")
    from datetime import datetime, timezone
    inicio_rodada = datetime.now(timezone.utc).isoformat()
    salvos = run_once()
    logging.info("Coleta concluida | registros salvos=%s", salvos)
    inicializar(DB)
    atualizar_pendentes(DB, editar_mensagem)

    # Apenas observacoes criadas nesta rodada: nao varrer partidas antigas.
    from analysis.goal_engine import minuto_numero
    from datetime import datetime, timezone
    contagem = Counter()
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        atuais = con.execute("""
            SELECT o.* FROM observacoes_live o
            JOIN (SELECT id_evento, MAX(id) ultimo FROM observacoes_live
                  GROUP BY id_evento) ult ON ult.ultimo=o.id
            WHERE o.status IN ('STATUS_FIRST_HALF','STATUS_SECOND_HALF')
              AND o.coletado_em_utc >= ?
            ORDER BY o.id DESC LIMIT ?
        """, (inicio_rodada, limite)).fetchall()
        for atual in atuais:
            evento = atual['id_evento']
            minuto = minuto_numero(atual['minuto'])
            status = atual['status']
            periodo = '1T' if status == 'STATUS_FIRST_HALF' else '2T'
            if minuto is None or not (5 <= minuto <= 14 if periodo == '1T' else 46 <= minuto <= 80):
                contagem['FORA_JANELA'] += 1
                continue
            # A pressao exige duas observacoes do mesmo tempo, sem contador regressivo.
            anteriores = con.execute("""
                SELECT minuto, finalizacoes_casa, finalizacoes_fora,
                       chutes_gol_casa, chutes_gol_fora
                FROM observacoes_live WHERE id_evento=? AND status=? AND id<?
                ORDER BY id DESC LIMIT 15
            """, (evento, status, atual['id'])).fetchall()
            avaliacao = None
            for ant in anteriores:
                m_ant = minuto_numero(ant['minuto'])
                if m_ant is None or not 0 < minuto - m_ant <= 10:
                    continue
                campos = ('finalizacoes_casa','finalizacoes_fora','chutes_gol_casa','chutes_gol_fora')
                if any(ant[c] is None or atual[c] is None for c in campos):
                    continue
                dif = {c: atual[c]-ant[c] for c in campos}
                if any(v < 0 for v in dif.values()):
                    continue
                finalizacoes = dif['finalizacoes_casa'] + dif['finalizacoes_fora']
                alvo = dif['chutes_gol_casa'] + dif['chutes_gol_fora']
                if finalizacoes >= 4 and alvo >= 1:
                    avaliacao = {'classificacao':'FORTE','novas_finalizacoes':finalizacoes,'novos_chutes_no_gol':alvo}
                    break
                if finalizacoes >= 3 and alvo >= 1:
                    avaliacao = {'classificacao':'BOA','novas_finalizacoes':finalizacoes,'novos_chutes_no_gol':alvo}
                    break
            if avaliacao is None:
                contagem['SEM_PRESSAO_CONFIRMADA'] += 1
                continue
            if ja_enviado(evento, periodo):
                contagem['JA_ENVIADO'] += 1
                continue
            texto, linha, gols = formatar_entrada(dict(atual), periodo)
            if not texto:
                contagem['DADOS_INCOMPLETOS'] += 1
                continue
            if os.getenv('GOALBOT_ENVIAR','0') == '1':
                message_id = enviar_mensagem(texto)
                registrar_sinal(DB, evento, periodo, message_id, texto, linha, gols)
                registrar_envio(evento, periodo)
                logging.info('%s | SINAL ENVIADO | %s | %s',evento,minuto,avaliacao)
            else:
                logging.info('%s | CANDIDATO (teste) | %s | %s',evento,minuto,avaliacao)
            contagem['CANDIDATO'] += 1
    logging.info('Jogos atuais=%s | Decisoes=%s', len(atuais), dict(contagem))
    logging.info("Telegram %s", "HABILITADO" if os.getenv("GOALBOT_ENVIAR", "0") == "1" else "DESATIVADO")


def main() -> None:
    parser = argparse.ArgumentParser(description='GOAL BOT AI - monitor ao vivo')
    parser.add_argument('--intervalo', type=int, default=120, help='Segundos entre rodadas (mínimo 60)')
    parser.add_argument('--limite', type=int, default=500, help='Máximo de partidas analisadas por rodada')
    parser.add_argument('--uma-vez', action='store_true', help='Executar uma rodada e sair')
    args = parser.parse_args()
    if args.intervalo < 60:
        parser.error('O intervalo mínimo é 60 segundos')
    if args.limite < 1:
        parser.error('O limite precisa ser positivo')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', stream=sys.stdout)
    logging.info('GOAL BOT AI | Monitor inteligente iniciado | intervalo=%ds | Telegram controlado por GOALBOT_ENVIAR', args.intervalo)
    if not args.uma_vez:
        iniciar_comandos(DB)
    try:
        while True:
            try:
                rodada(args.limite)
            except Exception:
                logging.exception('Erro na rodada; nenhuma entrada será enviada')
                if args.uma_vez:
                    raise
            if args.uma_vez:
                break
            logging.info('Próxima consulta em %d segundos', args.intervalo)
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        logging.info('Monitor encerrado pelo usuário')


if __name__ == '__main__':
    main()
