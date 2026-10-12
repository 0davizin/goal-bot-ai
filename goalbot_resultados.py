"""Registra sinais e atualiza resultado na mensagem original."""
import os
import json
from html import escape as html_escape
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from goalbot_historico import consultar as consultar_historico

DB_HISTORICO = Path(os.environ.get('GOALBOT_DB_PATH') or (Path(__file__).resolve().parent / 'goalbot.db' if Path(__file__).parent.name == 'database' else Path(__file__).resolve().parents[1] / 'database' / 'goalbot.db' if Path(__file__).parent.name in ('api','analysis') else Path(__file__).resolve().parent / 'database' / 'goalbot.db'))


def numero(valor):
    try:
        n = int(str(valor).strip())
        return n if n >= 0 else None
    except (ValueError, TypeError):
        return None


def minuto_num(valor):
    m = re.match(r"^(\d+)", str(valor or ""))
    return int(m.group(1)) if m else None


def inicializar(db):
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS sinais_telegram (
            id_evento TEXT NOT NULL, periodo TEXT NOT NULL,
            message_id INTEGER NOT NULL, texto_original TEXT NOT NULL,
            linha REAL NOT NULL, gols_inicio INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDENTE',
            criado_em TEXT NOT NULL, resultado TEXT,
            PRIMARY KEY(id_evento, periodo))""")


def formatar_entrada(row, periodo):
    try:
        d = json.loads(row['json_original'])
        home, away = d['home'], d['away']
        hs, aws = home['statistics'], away['statistics']
        nome_casa, nome_fora = home['name'], away['name']
        gols_casa, gols_fora = numero(home['score']), numero(away['score'])
        minuto = row['minuto']
        if not nome_casa or not nome_fora or gols_casa is None or gols_fora is None or minuto_num(minuto) is None:
            return None, None, None
        estatisticas = [numero(hs.get(k)) for k in ('totalShots','shotsOnTarget','wonCorners')] + [numero(aws.get(k)) for k in ('totalShots','shotsOnTarget','wonCorners')]
        if any(n is None for n in estatisticas):
            return None, None, None
        fc, ac, ec, ff, af, ef = estatisticas
        gols = gols_casa + gols_fora
        linha = gols + 0.5
        liga = d.get('league') or row.get('liga') or ''
        codigos = {'usa.1': 'Major League Soccer (MLS)',
                   'mex.1': 'Liga MX', 'eng.1': 'Premier League',
                   'esp.1': 'LaLiga', 'ger.1': 'Bundesliga',
                   'ita.1': 'Serie A', 'fra.1': 'Ligue 1'}
        liga_id = str(d.get('league_id') or '').strip().lower()
        liga = codigos.get(str(liga).strip().lower(), liga)
        if str(liga).strip().lower() in ('', 'all', 'campeonato não identificado'):
            liga = codigos.get(liga_id, '')
        if not liga:
            times = {str(nome_casa).strip().lower(), str(nome_fora).strip().lower()}
            if times == {'colorado rapids', 'san jose earthquakes'}:
                liga = 'Major League Soccer (MLS)'
            elif times == {'atlas', 'guadalajara'}:
                liga = 'Liga MX'
        cabecalho = f'🏆 {liga}\n' if liga else ''
        texto = (f"{cabecalho}{nome_casa} x {nome_fora}\n\n"
                 f"⏱️ {minuto}   |  {gols_casa} - {gols_fora}\n\n"
                 f"🎯 Over {linha:.1f}\n💎 Odd mínima 1.50\n\n"
                 f"👟 Finalizações | {fc} - {ff}\n"
                 f"🎯 No alvo | {ac} - {af}\n"
                 f"⛳ Escanteio | {ec} - {ef}")
        return texto, linha, gols
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, None, None


def registrar_sinal(db, evento, periodo, message_id, texto, linha, gols):
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        raise ValueError('Telegram não retornou message_id válido')
    with sqlite3.connect(db) as c:
        c.execute("""INSERT INTO sinais_telegram
            (id_evento,periodo,message_id,texto_original,linha,gols_inicio,status,criado_em)
            VALUES (?,?,?,?,?,?,'PENDENTE',?)""",
            (str(evento),periodo,message_id,texto,linha,gols,datetime.now(timezone.utc).isoformat()))


def atualizar_pendentes(db, editar):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        pendentes = c.execute("SELECT * FROM sinais_telegram WHERE status='PENDENTE'").fetchall()
        for s in pendentes:
            atual = c.execute("""SELECT * FROM observacoes_live
                WHERE id_evento=? ORDER BY id DESC LIMIT 1""", (s['id_evento'],)).fetchone()
            if not atual:
                continue
            gc, gf = numero(atual['placar_casa']), numero(atual['placar_fora'])
            if gc is None or gf is None:
                continue
            try:
                coletado = datetime.fromisoformat(atual['coletado_em_utc'].replace('Z', '+00:00'))
                enviado = datetime.fromisoformat(s['criado_em'].replace('Z', '+00:00'))
                if coletado <= enviado:
                    continue
            except (ValueError, TypeError):
                continue
            status, minuto = atual['status'], atual['minuto']
            total = gc + gf
            if s['periodo'] == '1T':
                if status in ('STATUS_FIRST_HALF', 'STATUS_HALFTIME'):
                    if total > s['gols_inicio']:
                        rotulo = 'GREEN✅'
                    elif status == 'STATUS_HALFTIME':
                        rotulo = 'RED❌'
                    else:
                        continue
                elif status in ('STATUS_SECOND_HALF', 'STATUS_FULL_TIME') and total <= s['gols_inicio']:
                    rotulo = 'RED❌'
                else:
                    continue
            elif s['periodo'] == '2T':
                if total > s['gols_inicio']:
                    rotulo = 'GREEN✅'
                elif status == 'STATUS_FULL_TIME':
                    rotulo = 'RED❌'
                else:
                    continue
            else:
                continue
            rotulo_visual = 'GOOL✅' if rotulo == 'GREEN✅' else rotulo
            linha_resultado = f"🎖️ Resultado: {minuto} | {gc} - {gf} | {rotulo_visual}"
            try:
                editar(s['message_id'], html_escape(s['texto_original']) + '\n\n<b>' + html_escape(linha_resultado) + '</b>')
            except Exception:
                logging.exception('Falha ao editar mensagem do evento %s', s['id_evento'])
                continue
            c.execute("UPDATE sinais_telegram SET status=?, resultado=? WHERE id_evento=? AND periodo=?",
                      (rotulo, linha_resultado, s['id_evento'], s['periodo']))
            c.commit()
