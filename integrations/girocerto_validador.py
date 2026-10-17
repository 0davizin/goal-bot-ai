"""Validação conservadora de odds públicas da Giro Certo; não gera bilhetes."""
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup
import requests

from integrations.girocerto import SPORTS_URL, TIMEOUT, _odd

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; GoalBotAI/1.0)'}


@dataclass(frozen=True)
class Validacao:
    aprovado: bool
    motivo: str
    odd: float | None = None
    url_partida: str | None = None


def _normalizar(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^a-z0-9]+', ' ', s.casefold()).strip()
    return ' '.join(w for w in s.split() if w not in ('fc', 'cf', 'sc', 'ac', 'club', 'clube', 'de', 'do', 'da'))


def _placar(team):
    t = team.select_one('.sb-ev__score')
    if t is None or not t.get_text(strip=True).isdigit():
        return None
    return int(t.get_text(strip=True))


def _eventos(soup):
    vistos = set()
    for artigo in soup.select('article.sb-ev[data-live]'):
        link = artigo.select_one('a.sb-ev__teams[href*="jogo="]')
        if link is None:
            continue
        href = link.get('href', '')
        parsed = urlparse(href)
        ids = parse_qs(parsed.query).get('jogo', [])
        if len(ids) != 1 or not re.fullmatch(r'[0-9a-fA-F-]{36}', ids[0]):
            continue
        if ids[0] in vistos:
            continue
        vistos.add(ids[0])
        teams = artigo.select('.sb-ev__teams .sb-ev__team')
        if len(teams) != 2:
            continue
        nomes = [t.select_one('.sb-ev__name') for t in teams]
        if any(n is None for n in nomes):
            continue
        liga = artigo.select_one('.sb-tag[href]')
        slug = liga.get('href', '').lower() if liga else ''
        # Filtro negativo apenas; a validação definitiva exige identidade e placar.
        if any(s in slug for s in ('nba', 'nhl', 'basket', 'hockey', 'tennis', 'baseball', 'nfl', 'esport')):
            continue
        yield (ids[0], [n.get_text(' ', strip=True) for n in nomes], [_placar(t) for t in teams], artigo)


def validar_odd(row, periodo, linha, minima=1.50, session=None):
    """Aprova só com partida única, placar idêntico e linha/período explícitos."""
    try:
        d = json.loads(row['json_original'])
        nomes = [d['home']['name'], d['away']['name']]
        gols = [int(d['home']['score']), int(d['away']['score'])]
        if any(not _normalizar(n) for n in nomes):
            return Validacao(False, 'nomes ESPN ausentes')
        if periodo not in ('1T', '2T'):
            return Validacao(False, 'período desconhecido')
        get = session.get if session else requests.get
        r = get(SPORTS_URL, timeout=TIMEOUT, headers=HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        candidatos = [(id_, art) for id_, ns, ps, art in _eventos(soup)
                      if [_normalizar(n) for n in ns] == [_normalizar(n) for n in nomes] and ps == gols]
        if len(candidatos) != 1:
            return Validacao(False, 'partida/placar não confirmado de forma única')
        event_id, _ = candidatos[0]
        url = SPORTS_URL + '?jogo=' + event_id
        detalhe = get(url, timeout=TIMEOUT, headers=HEADERS)
        detalhe.raise_for_status()
        doc = BeautifulSoup(detalhe.text, 'html.parser')
        box = doc.select_one('div.sb-detail')
        if box is None:
            return Validacao(False, 'detalhe indisponível')
        correspondentes = []
        for botao in box.select('button.sb-odd'):
            odd = _odd(botao)
            if odd is None:
                continue
            mercado = _normalizar(odd.mercado)
            selecao = _normalizar(odd.selecao)
            if not re.fullmatch(r'mais ' + re.escape(f'{float(linha):.1f}'.replace('.', ' ')), selecao):
                continue
            primeiro_tempo = bool(re.search(r'(primeiro tempo|1 tempo|1t|half time|first half)', mercado))
            if periodo == '1T':
                if not primeiro_tempo or 'gol' not in mercado:
                    continue
            else:
                if mercado != 'total de gols':
                    continue
            correspondentes.append(odd.valor)
        if len(correspondentes) != 1:
            return Validacao(False, 'mercado/linha indisponível ou ambíguo')
        valor = correspondentes[0]
        if valor < minima:
            return Validacao(False, f'odd {valor:.2f} abaixo de {minima:.2f}', valor, url)
        return Validacao(True, 'cotação pública observada; execução não garantida', valor, url)
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
        logging.warning('Giro Certo indisponível: %s', type(exc).__name__)
        return Validacao(False, 'falha na validação da Giro Certo')
