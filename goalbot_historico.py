"""Historico local verificavel; nunca altera o motor de selecao.

Gol HT: partidas com placar registrado em STATUS_HALFTIME.
Over Limite: sinais anteriores concluidos na mesma linha e periodo, envolvendo
uma das equipes. Sao metricas diferentes, nao previsoes de probabilidade.
"""
import json
import sqlite3


def _times(raw):
    try:
        data = json.loads(raw)
        return {str(data[s]['name']).strip().casefold() for s in ('home', 'away')}
    except (KeyError, TypeError, ValueError, AttributeError):
        return set()


def _int(value):
    try:
        n = int(value)
        return n if n >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _formatar(acertos, total):
    return f'{acertos}/{total} - {acertos * 100 / total:.0f}%' if total else 'Historico indisponível'


def consultar(db, evento, periodo, linha, nome_casa, nome_fora, max_jogos=10):
    """Retorna amostra dos ultimos dez jogos verificaveis envolvendo os times.

    Para 2T usa o desfecho de sinais anteriores da MESMA linha; nao infere
    sucesso de alerta a partir de placar final de jogo sem sinal.
    """
    procurados = {str(nome_casa).strip().casefold(), str(nome_fora).strip().casefold()}
    if not all(procurados):
        return 'Historico indisponível'
    try:
        with sqlite3.connect(db, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            if periodo == '1T':
                rows = conn.execute('''SELECT id_evento, casa, fora, gols_ht
                    FROM historico_gols WHERE id_evento<>?
                    ORDER BY COALESCE(data_jogo, atualizado_utc) DESC''', (str(evento),)).fetchall()
                acertos = total = 0
                for r in rows:
                    if not (procurados & {str(r['casa']).casefold(), str(r['fora']).casefold()}):
                        continue
                    total += 1
                    acertos += int(r['gols_ht'] > float(linha))
                    if total >= max_jogos:
                        break
                return _formatar(acertos, total)

            if periodo == '2T':
                # Mesmo mercado e mesma linha, apenas sinais ja resolvidos.
                rows = conn.execute('''
                    SELECT s.id_evento, s.status, o.json_original
                    FROM sinais_telegram s
                    JOIN observacoes_live o ON o.id=(
                        SELECT MAX(o2.id) FROM observacoes_live o2
                        WHERE o2.id_evento=s.id_evento)
                    WHERE s.periodo='2T' AND ABS(s.linha - ?) < 0.001
                      AND s.status IN ('GREEN✅', 'RED❌') AND s.id_evento<>?
                    ORDER BY s.criado_em DESC
                ''', (float(linha), str(evento))).fetchall()
                vistos = set()
                acertos = total = 0
                for r in rows:
                    if r['id_evento'] in vistos or not (procurados & _times(r['json_original'])):
                        continue
                    vistos.add(r['id_evento'])
                    total += 1
                    acertos += r['status'].startswith('GREEN')
                    if total >= max_jogos:
                        break
                return _formatar(acertos, total)
    except (sqlite3.Error, ValueError, TypeError):
        pass
    return 'Historico indisponível'
