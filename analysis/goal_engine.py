"""GOAL BOT AI: avaliação preliminar de pressão ofensiva.

Não estima probabilidade de gol nem recomenda apostas automaticamente.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

DB_DEFAULT = Path(__file__).resolve().parents[1] / 'database' / 'goalbot.db'


def minuto_numero(valor):
    """Converte o relógio da partida em minutos decorridos."""
    import re

    if valor is None:
        return None

    texto = str(valor).strip()
    partes = re.fullmatch(
        r"(\d+)\s*'?\s*(?:\+\s*(\d+)\s*'?)?",
        texto
    )

    if not partes:
        return None

    return int(partes.group(1)) + int(partes.group(2) or 0)


def avaliar_jogo(registros):
    """Retorna avaliação a partir dos dois snapshots mais recentes válidos."""
    if len(registros) < 2:
        return {'classificacao': 'DADOS_INSUFICIENTES', 'motivo': 'Menos de duas observações'}
    anterior, atual = registros[-2:]
    m0, m1 = minuto_numero(anterior['minuto']), minuto_numero(atual['minuto'])
    if m0 is None or m1 is None or m1 <= m0:
        return {'classificacao': 'DADOS_INSUFICIENTES', 'motivo': 'Minutos insuficientes ou inconsistentes'}
    intervalo = m1 - m0
    if intervalo > 10:
        return {'classificacao': 'DADOS_INSUFICIENTES', 'motivo': 'Intervalo superior a 10 minutos'}
    campos = ('finalizacoes_casa', 'finalizacoes_fora', 'chutes_gol_casa', 'chutes_gol_fora')
    if any(anterior[c] is None or atual[c] is None for c in campos):
        return {'classificacao': 'DADOS_INSUFICIENTES', 'motivo': 'Estatísticas essenciais ausentes'}
    dif = {c: atual[c] - anterior[c] for c in campos}
    if any(v < 0 for v in dif.values()):
        return {'classificacao': 'DADOS_INSUFICIENTES', 'motivo': 'Contadores retrocederam; possível correção da fonte'}
    finalizacoes = dif['finalizacoes_casa'] + dif['finalizacoes_fora']
    no_alvo = dif['chutes_gol_casa'] + dif['chutes_gol_fora']
    # Limiares exploratórios: NÃO são probabilidades calibradas.
    if finalizacoes >= 4 and no_alvo >= 2 and intervalo <= 5:
        classe = 'FORTE'
    elif finalizacoes >= 3 and no_alvo >= 1 and intervalo <= 6:
        classe = 'BOA'
    elif finalizacoes >= 1:
        classe = 'MONITORAR'
    else:
        classe = 'EVITAR'
    return {'classificacao': classe, 'intervalo_min': intervalo,
            'novas_finalizacoes': finalizacoes, 'novos_chutes_no_gol': no_alvo,
            'motivo': 'Classificação experimental; não é sinal de aposta'}


def analisar_banco(db_path=DB_DEFAULT, limite=10):
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        ids = [r[0] for r in con.execute('''
            SELECT id_evento FROM observacoes_live
            GROUP BY id_evento HAVING COUNT(*) >= 2
            ORDER BY MAX(coletado_em_utc) DESC LIMIT ?
        ''', (limite,))]
        resultados = []
        for evento in ids:
            registros = [dict(r) for r in con.execute('''
                SELECT minuto, finalizacoes_casa, finalizacoes_fora,
                       chutes_gol_casa, chutes_gol_fora, coletado_em_utc
                FROM observacoes_live WHERE id_evento = ?
                ORDER BY coletado_em_utc DESC LIMIT 2
            ''', (evento,))][::-1]
            resultados.append((evento, registros[-1]['minuto'], avaliar_jogo(registros)))
        return resultados


def main():
    parser = argparse.ArgumentParser(description='Teste local do motor de pressão ofensiva')
    parser.add_argument('--limite', type=int, default=10)
    args = parser.parse_args()
    for evento, minuto, resultado in analisar_banco(limite=max(1, min(args.limite, 100))):
        print(f'JOGO {evento} | {minuto} | {resultado}')
    print('MODO TESTE: Telegram desativado; nenhuma entrada gerada.')


if __name__ == '__main__':
    main()
