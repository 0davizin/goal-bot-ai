"""Leitura conservadora de partidas e odds públicas da Giro Certo.

Não é API oficial. O HTML pode mudar; nenhuma odd é garantida ou executável.
Este módulo NÃO cria bilhetes nem efetua apostas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://girocerto.io"
SPORTS_URL = BASE_URL + "/esportes"
TIMEOUT = 20


@dataclass(frozen=True)
class Odd:
    mercado: str
    selecao: str
    valor: float


@dataclass(frozen=True)
class Partida:
    nome: str
    url: str
    ao_vivo: bool
    odds: tuple[Odd, ...]


def _texto(elemento) -> str:
    return elemento.get_text(" ", strip=True)


def _odd(botao) -> Optional[Odd]:
    if botao.has_attr("disabled") or botao.get("aria-disabled") == "true":
        return None
    classes = botao.get("class", [])
    if any("lock" in c.lower() or "disabled" in c.lower() for c in classes):
        return None
    aria = botao.get("aria-label", "")
    # Exemplo: 'Total de gols: Mais de 4.5, cotação 2.64'
    m = re.search(r"^(.+?):\s*(.+?),\s*cota(?:ç|c)[aã]o\s*(\d+(?:[.,]\d+)?)\s*$", aria, re.I)
    if not m:
        return None
    valor = float(m.group(3).replace(",", "."))
    if not 1.0 < valor < 10000:
        return None
    return Odd(m.group(1).strip(), m.group(2).strip(), valor)


def analisar_html(html: str) -> list[Partida]:
    """Extrai jogos e odds visíveis da página pública, sem inferir mercados ausentes."""
    soup = BeautifulSoup(html, "html.parser")
    saida: list[Partida] = []
    for artigo in soup.select("article.sb-ev"):
        ancora = artigo.select_one('a[href*="jogo="]')
        if ancora is None:
            continue
        url = urljoin(BASE_URL, ancora.get("href", ""))
        if not url.startswith(SPORTS_URL + "?jogo="):
            continue
        nome = _texto(artigo)
        if not nome:
            continue
        odds = tuple(o for b in artigo.select("button.sb-odd") if (o := _odd(b)) is not None)
        # data-live indica live na interface; não basta haver minuto no texto.
        ao_vivo = artigo.has_attr("data-live")
        saida.append(Partida(nome=nome, url=url, ao_vivo=ao_vivo, odds=odds))
    return saida


def consultar_partidas(*, somente_ao_vivo: bool = False) -> list[Partida]:
    resposta = requests.get(
        SPORTS_URL,
        timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; GoalBotAI/1.0)"},
    )
    resposta.raise_for_status()
    partidas = analisar_html(resposta.text)
    return [p for p in partidas if p.ao_vivo] if somente_ao_vivo else partidas


def consultar_detalhe(url: str) -> tuple[Odd, ...]:
    """Consulta odds visíveis do detalhe. URL precisa pertencer à Giro Certo."""
    if not re.fullmatch(r"https://girocerto\.io/esportes\?jogo=[0-9a-fA-F-]{36}", url):
        raise ValueError("URL de partida Giro Certo inválida")
    resposta = requests.get(url, timeout=TIMEOUT)
    resposta.raise_for_status()
    soup = BeautifulSoup(resposta.text, "html.parser")
    detalhe = soup.select_one("div.sb-detail")
    if detalhe is None:
        return ()
    return tuple(o for b in detalhe.select("button.sb-odd") if (o := _odd(b)) is not None)


if __name__ == "__main__":
    partidas = consultar_partidas()
    print(f"Partidas listadas: {len(partidas)} | ao vivo: {sum(p.ao_vivo for p in partidas)}")
    for p in partidas:
        print(f"{'AO VIVO' if p.ao_vivo else 'FUTURO'} | {p.nome[:100]} | {p.url}")
        for o in p.odds:
            if "gol" in o.mercado.casefold():
                print(f"  {o.mercado} / {o.selecao}: {o.valor:.2f}")
