"""Coleta independente de gols HT/2T via ESPN summary. Nunca decide sinais."""
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import requests

DB = Path(__file__).resolve().parent / 'database' / 'goalbot.db'
BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer'


def preparar(db=DB):
    with sqlite3.connect(db, timeout=15) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS historico_gols (
          id_evento TEXT PRIMARY KEY, casa TEXT NOT NULL, fora TEXT NOT NULL,
          liga TEXT, gols_ht INTEGER NOT NULL, gols_2t INTEGER NOT NULL,
          gols_ft INTEGER NOT NULL, placar_casa INTEGER, placar_fora INTEGER,
          data_jogo TEXT, atualizado_utc TEXT NOT NULL, fonte TEXT NOT NULL)''')


def _inteiro(x):
    try:
        v = int(str(x))
        return v if v >= 0 else None
    except (ValueError, TypeError):
        return None


def _resumo(evento, liga):
    # O scoreboard global nao informa sempre a liga no formato textual.
    # Tenta primeiro o endpoint global; em seguida ligas conhecidas.
    nomes = {str((evento.get('home') or {}).get('name', '')).casefold(),
             str((evento.get('away') or {}).get('name', '')).casefold()}
    opcoes = [liga] if liga and liga != 'all' else ['all']
    if {'atlas', 'guadalajara'} & nomes:
        opcoes.append('mex.1')
    if {'colorado rapids', 'san jose earthquakes'} & nomes:
        opcoes.append('usa.1')
    for codigo in dict.fromkeys(opcoes):
        try:
            r = requests.get(f'{BASE}/{codigo}/summary', params={'event': evento['id']}, timeout=12)
            if not r.ok:
                continue
            d = r.json()
            if isinstance(d.get('keyEvents'), list) and d['keyEvents']:
                return d, codigo
        except (requests.RequestException, ValueError, TypeError):
            continue
    return None, None


def _contar(d, placar_final):
    eventos = d.get('keyEvents') or []
    if not eventos:
        return None
    gols_ht = gols_2t = 0
    houve_intervalo = any(str((e.get('type') or {}).get('text', '')).lower() == 'halftime' for e in eventos)
    for e in eventos:
        tipo = str((e.get('type') or {}).get('text') or '').casefold()
        if not (tipo == 'goal' or tipo.startswith('goal -')):
            continue
        clock = str((e.get('clock') or {}).get('displayValue') or '')
        m = re.match(r'^\s*(\d+)', clock)
        if not m:
            return None
        minuto = int(m.group(1))
        # 45+N pertence ao primeiro tempo; 90+N ao segundo.
        if minuto < 45 or (minuto == 45 and '+' in clock) or minuto == 45:
            gols_ht += 1
        else:
            gols_2t += 1
    if gols_ht + gols_2t != placar_final or not houve_intervalo:
        return None
    return gols_ht, gols_2t


def coletar(jogos, db=DB, max_consultas=12):
    preparar(db)
    completos = [g for g in jogos if g.get('status') == 'STATUS_FULL_TIME' and g.get('id')]
    with sqlite3.connect(db, timeout=15) as c:
        existentes = {r[0] for r in c.execute('SELECT id_evento FROM historico_gols')}
    # Partidas recentes primeiro, com duas partidas conhecidas priorizadas no backfill.
    pendentes = [g for g in completos if str(g['id']) not in existentes]
    pendentes.sort(key=lambda g: (str(g['id']) in ('401876951', '761857'), str(g.get('event_date') or '')), reverse=True)
    salvos = 0
    for g in pendentes[:max_consultas]:
        casa, fora = g.get('home') or {}, g.get('away') or {}
        a, b = _inteiro(casa.get('score')), _inteiro(fora.get('score'))
        if a is None or b is None or not casa.get('name') or not fora.get('name'):
            continue
        d, liga = _resumo(g, g.get('league'))
        if not d:
            continue
        contagem = _contar(d, a + b)
        if contagem is None:
            continue
        ht, segundo = contagem
        with sqlite3.connect(db, timeout=15) as c:
            c.execute('''INSERT OR IGNORE INTO historico_gols
              (id_evento,casa,fora,liga,gols_ht,gols_2t,gols_ft,placar_casa,placar_fora,data_jogo,atualizado_utc,fonte)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
              (str(g['id']), casa['name'], fora['name'], liga, ht, segundo, a+b, a, b,
               g.get('event_date'), datetime.now(timezone.utc).isoformat(), 'ESPN_SUMMARY_KEYEVENTS'))
            salvos += c.total_changes
    logging.info('Historico gols ESPN | consultados=%d | gravados=%d | pendentes=%d',
                 min(max_consultas, len(pendentes)), salvos, len(pendentes))
    return salvos
