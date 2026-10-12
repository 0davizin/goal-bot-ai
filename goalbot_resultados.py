"""Registra sinais e atualiza resultado na mensagem original."""
import os
import json
from html import escape as html_escape
import logging
import re
import sqlite3
import requests
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


# A ESPN não garante odds live para todos os campeonatos.
# Nunca converter odds pré-jogo em odds ao vivo.
PAISES = {
    'mex': ('🇲🇽', 'MÉXICO'), 'usa': ('🇺🇸', 'ESTADOS UNIDOS'),
    'eng': ('🏴', 'INGLATERRA'), 'esp': ('🇪🇸', 'ESPANHA'),
    'ger': ('🇩🇪', 'ALEMANHA'), 'ita': ('🇮🇹', 'ITÁLIA'),
    'fra': ('🇫🇷', 'FRANÇA'), 'bra': ('🇧🇷', 'BRASIL'),
    'arg': ('🇦🇷', 'ARGENTINA'), 'por': ('🇵🇹', 'PORTUGAL'),
    'ned': ('🇳🇱', 'HOLANDA'), 'bel': ('🇧🇪', 'BÉLGICA'),
    'tur': ('🇹🇷', 'TURQUIA'), 'sco': ('🏴', 'ESCÓCIA'),
    'col': ('🇨🇴', 'COLÔMBIA'), 'uru': ('🇺🇾', 'URUGUAI'),
    'chi': ('🇨🇱', 'CHILE'), 'per': ('🇵🇪', 'PERU'),
    'ecu': ('🇪🇨', 'EQUADOR'), 'jpn': ('🇯🇵', 'JAPÃO'),
    'kor': ('🇰🇷', 'COREIA DO SUL'), 'aus': ('🇦🇺', 'AUSTRÁLIA'),
    'ksa': ('🇸🇦', 'ARÁBIA SAUDITA'), 'sa': ('🌎', 'AMÉRICA DO SUL'),
    'uefa': ('🌍', 'EUROPA'), 'concacaf': ('🌎', 'CONCACAF'),
    'afc': ('🌏', 'ÁSIA'), 'caf': ('🌍', 'ÁFRICA'),
    'fifa': ('🌍', 'INTERNACIONAL'),
}
NOMES_LIGAS = {
    'usa.1': 'MAJOR LEAGUE SOCCER (MLS)', 'mex.1': 'LIGA MX',
    'eng.1': 'PREMIER LEAGUE', 'esp.1': 'LALIGA',
    'esp.2': 'LALIGA HYPERMOTION (SEGUNDA DIVISIÓN)',
    'ger.1': 'BUNDESLIGA', 'ita.1': 'SERIE A',
    'fra.1': 'LIGUE 1', 'bra.1': 'BRASILEIRÃO SÉRIE A',
    'arg.1': 'PRIMERA DIVISIÓN', 'por.1': 'PRIMEIRA LIGA',
    'uefa.champions': 'CHAMPIONS LEAGUE',
    'uefa.europa': 'EUROPA LEAGUE',
    'conmebol.libertadores': 'COPA LIBERTADORES',
    'conmebol.sudamericana': 'COPA SUL-AMERICANA',
}


def _cabecalho_liga(d, row):
    """Prefere metadados da competição; IDs numéricos não identificam países."""
    liga_dado = d.get('league') or row.get('liga') or ''
    liga_id = str(d.get('league_id') or d.get('leagueId') or '').strip().lower()
    if isinstance(liga_dado, dict):
        liga_id = str(liga_dado.get('slug') or liga_id).strip().lower()
        liga_dado = liga_dado.get('displayName') or liga_dado.get('name') or ''
    nome_bruto = str(liga_dado).strip()
    if nome_bruto.lower() in ('all', 'none', 'campeonato não identificado') or nome_bruto.isdigit():
        nome_bruto = ''
    nome = NOMES_LIGAS.get(liga_id) or NOMES_LIGAS.get(nome_bruto.lower()) or nome_bruto.upper()
    if not nome:
        nome = 'COMPETIÇÃO NÃO IDENTIFICADA'
    if liga_id.startswith('conmebol') or 'libertadores' in liga_id or 'sudamericana' in liga_id:
        bandeira, pais = '🌎', 'AMÉRICA DO SUL'
    elif liga_id.startswith('uefa.'):
        bandeira, pais = '🌍', 'EUROPA'
    else:
        codigo = liga_id.split('.')[0]
        bandeira, pais = PAISES.get(codigo, ('🏆', ''))
    return f'{bandeira} {nome}' + (f' - {pais}' if pais else '')


def _odd_live_espn(d, row, linha):
    """Consulta cotação ESPN em TESTE, sem presumir disponibilidade ao vivo.

    Aceita somente o Over do total de gols da partida, com linha idêntica
    à recomendada. A ESPN pode devolver odds de pré-jogo no campo `current`.
    """
    liga_id = str(d.get('league_id') or d.get('leagueId') or '').strip().lower()
    liga = d.get('league')
    if not liga_id and isinstance(liga, dict):
        liga_id = str(liga.get('slug') or liga.get('id') or '').strip().lower()
    evento = str(row.get('id_evento') or d.get('id') or '').strip()
    if not re.fullmatch(r'[a-z0-9_.-]+', liga_id) or not re.fullmatch(r'\d+', evento):
        return None
    url = (f'https://sports.core.api.espn.com/v2/sports/soccer/leagues/{liga_id}'
           f'/events/{evento}/competitions/{evento}/odds')
    try:
        resposta = requests.get(url, timeout=4, headers={'Accept': 'application/json'})
        resposta.raise_for_status()
        payload = resposta.json()
    except (requests.RequestException, ValueError) as exc:
        logging.debug('Odds ESPN indisponíveis para %s: %s', evento, exc)
        return None
    if not isinstance(payload, dict):
        return None
    for item in payload.get('items', []):
        if not isinstance(item, dict):
            continue
        atual = item.get('current')
        if not isinstance(atual, dict):
            continue
        total = atual.get('total')
        if not isinstance(total, dict):
            continue
        try:
            linha_espn = float(total.get('american') or total.get('alternateDisplayValue'))
            if abs(linha_espn - float(linha)) > 0.001:
                continue
            over = atual.get('over')
            if not isinstance(over, dict):
                continue
            odd = float(over['decimal'])
            if 1.01 <= odd <= 100.0:
                return odd
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return None


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
        cabecalho = _cabecalho_liga(d, row)
        odd = _odd_live_espn(d, row, linha)
        linha_odd = (f'🧪 Odd ESPN em teste: {odd:.2f} (não confirmada ao vivo)\n💎 Odd mínima recomendada: 1.50'
                     if odd is not None else '💎 Odd mínima recomendada: 1.50')
        texto = (f'{cabecalho}\n{nome_casa} x {nome_fora}\n\n'
                 f'⏱️ {minuto}   |  {gols_casa} - {gols_fora}\n\n'
                 f'🎯 Over {linha:.1f}\n{linha_odd}\n\n'
                 f'👟 Finalizações | {fc} - {ff}\n'
                 f'🎯 No alvo | {ac} - {af}\n'
                 f'⛳ Escanteio | {ec} - {ef}')
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
    """Reconcilia placares, inclusive GREENs antigos que podem ter sido anulados.

    O gol ao vivo é PROVISÓRIO. Somente o placar do encerramento do período
    transforma a entrada em GREEN/RED definitivo. Uma observação posterior
    do mesmo encerramento pode corrigir uma decisão anterior (ex.: VAR).
    """
    with sqlite3.connect(db, timeout=15) as c:
        c.row_factory = sqlite3.Row
        sinais = c.execute("""SELECT * FROM sinais_telegram
            WHERE status IN ('PENDENTE', 'CONFIRMANDO', 'GREEN✅', 'RED❌')""").fetchall()
        for s in sinais:
            # A observação mais recente pode corrigir um placar anterior.
            atual = c.execute("""SELECT * FROM observacoes_live
                WHERE id_evento=? ORDER BY id DESC LIMIT 1""", (s['id_evento'],)).fetchone()
            if atual is None:
                continue
            gc, gf = numero(atual['placar_casa']), numero(atual['placar_fora'])
            if gc is None or gf is None:
                continue
            try:
                coletado = datetime.fromisoformat(str(atual['coletado_em_utc']).replace('Z', '+00:00'))
                enviado = datetime.fromisoformat(str(s['criado_em']).replace('Z', '+00:00'))
                if coletado <= enviado:
                    continue
            except (ValueError, TypeError):
                continue

            status = str(atual['status'])
            periodo = s['periodo']
            minuto = atual['minuto']
            gols_inicio = s['gols_inicio']
            final = False
            if periodo == '1T':
                # Não utilizar placar do 2T para liquidar entrada do 1T.
                if status == 'STATUS_FIRST_HALF':
                    placar = (gc, gf)
                else:
                    ht = c.execute("""SELECT * FROM observacoes_live
                        WHERE id_evento=? AND status='STATUS_HALFTIME'
                        ORDER BY id DESC LIMIT 1""", (s['id_evento'],)).fetchone()
                    if ht is None:
                        # Sem placar de intervalo verificável: não inventar resultado.
                        continue
                    hc, hf = numero(ht['placar_casa']), numero(ht['placar_fora'])
                    if hc is None or hf is None:
                        continue
                    placar = (hc, hf)
                    minuto = ht['minuto']
                    final = True
                if status == 'STATUS_HALFTIME':
                    placar = (gc, gf)
                    final = True
            elif periodo == '2T':
                if status not in ('STATUS_SECOND_HALF', 'STATUS_FULL_TIME'):
                    continue
                placar = (gc, gf)
                final = status == 'STATUS_FULL_TIME'
            else:
                continue

            total = sum(placar)
            if final:
                novo_status = 'GREEN✅' if total > gols_inicio else 'RED❌'
                rotulo = 'GOOL✅' if novo_status == 'GREEN✅' else 'RED❌'
                if novo_status == 'RED❌':
                    # Somente RED tem minuto padronizado, nunca durante o jogo.
                    minuto_resultado = '45' if periodo == '1T' else '90'
                else:
                    # Preserva o minuto real do gol. Se houve VAR, utiliza o
                    # primeiro registro da sequência positiva que permaneceu.
                    minuto_resultado = minuto
                    historico = c.execute("""SELECT minuto, placar_casa, placar_fora, status
                        FROM observacoes_live
                        WHERE id_evento=? AND coletado_em_utc>?
                        ORDER BY id DESC LIMIT 300""",
                        (s['id_evento'], s['criado_em'])).fetchall()
                    sequencia = []
                    for obs in historico:
                        if periodo == '1T' and obs['status'] not in ('STATUS_FIRST_HALF', 'STATUS_HALFTIME'):
                            continue
                        if periodo == '2T' and obs['status'] not in ('STATUS_SECOND_HALF', 'STATUS_FULL_TIME'):
                            continue
                        oc, of = numero(obs['placar_casa']), numero(obs['placar_fora'])
                        if oc is None or of is None:
                            continue
                        if oc + of <= gols_inicio:
                            break
                        sequencia.append(obs['minuto'])
                    if sequencia:
                        minuto_resultado = sequencia[-1]
                linha_resultado = f"🎖️ Resultado: {minuto_resultado} | {placar[0]} - {placar[1]} | {rotulo}"
            elif total > gols_inicio:
                novo_status = 'CONFIRMANDO'
                linha_resultado = (f"⏳ Gol em confirmação: {minuto} | "
                                   f"{placar[0]} - {placar[1]} | Aguardando validação")
            else:
                novo_status = 'PENDENTE'
                # Remove resultado anterior do Telegram se gol foi anulado.
                linha_resultado = None

            # Não reeditar a mensagem a cada minuto se o placar provisório
            # permaneceu igual. O minuto exibido é o da primeira detecção.
            if novo_status == 'CONFIRMANDO' and s['status'] == 'CONFIRMANDO' and s['resultado']:
                anterior = str(s['resultado'])
                placar_anterior = re.search(r'\|\s*(\d+)\s*-\s*(\d+)\s*\|', anterior)
                if (placar_anterior and
                    (int(placar_anterior.group(1)), int(placar_anterior.group(2))) == placar):
                    linha_resultado = anterior

            if novo_status == s['status'] and linha_resultado == s['resultado']:
                continue
            texto = html_escape(s['texto_original'])
            if linha_resultado:
                texto += '\n\n<b>' + html_escape(linha_resultado) + '</b>'
            try:
                editar(s['message_id'], texto)
            except Exception:
                logging.exception('Falha ao reconciliar sinal do evento %s', s['id_evento'])
                continue
            c.execute("""UPDATE sinais_telegram SET status=?, resultado=?
                WHERE id_evento=? AND periodo=?""",
                (novo_status, linha_resultado, s['id_evento'], periodo))
            c.commit()


def relatorio_status(db, periodo='dia'):
    """Relatório por data de envio, fuso America/Sao_Paulo; retorno simulado."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    agora = datetime.now(ZoneInfo('America/Sao_Paulo'))
    if periodo == 'dia':
        inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        fim = inicio + timedelta(days=1)
        titulo = 'DIÁRIO | ' + inicio.strftime('%d/%m/%Y')
    elif periodo == 'mes':
        inicio = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fim = inicio.replace(year=inicio.year + 1, month=1) if inicio.month == 12 else inicio.replace(month=inicio.month + 1)
        titulo = 'MENSAL | ' + inicio.strftime('%m/%Y')
    elif periodo == 'geral':
        inicio, fim = None, None
        titulo = 'GERAL | HISTÓRICO'
    else:
        raise ValueError('Período inválido')
    with sqlite3.connect(db, timeout=15) as c:
        if inicio is None:
            linhas = c.execute('SELECT status FROM sinais_telegram').fetchall()
        else:
            linhas = c.execute(
                'SELECT status FROM sinais_telegram WHERE criado_em >= ? AND criado_em < ?',
                (inicio.astimezone(timezone.utc).isoformat(), fim.astimezone(timezone.utc).isoformat())
            ).fetchall()
    total = len(linhas)
    green = sum(1 for (s,) in linhas if str(s).startswith('GREEN'))
    red = sum(1 for (s,) in linhas if str(s).startswith('RED'))
    pendentes = total - green - red
    resolvidas = green + red
    margem = 100 * green / resolvidas if resolvidas else 0
    stake = 10.0
    odd = 1.50
    lucro = green * stake * (odd - 1) - red * stake
    apostado = resolvidas * stake
    roi = 100 * lucro / apostado if apostado else 0
    def reais(n):
        return 'R$ ' + f'{n:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return (f'📊 GOAL BOT AI | {titulo}\n\n'
            f'🎫 Entradas: {total}\n'
            f'🤑 Green: {green}\n'
            f'🥴 Red: {red}\n'
            f'⏳ Pendentes: {pendentes}\n'
            f'📍 Margem: {margem:.2f}%\n'
            f'💰 Sobre banca: {reais(100 + lucro)}\n'
            f'💲 ROI: {roi:+.2f}%\n'
            f'💵 Lucro líquido: {reais(lucro)}\n'
            f'📈 Total apostado: {reais(apostado)}\n\n'
            '🧮 Simulação: R$ 10/entrada, odd fixa 1,50.\n'
            'Banca-base R$ 100; não representa saldo real.\n'
            'Margem calculada somente sobre entradas resolvidas.')
