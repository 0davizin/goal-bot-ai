import sqlite3
from pathlib import Path

from analysis.goal_engine import analisar_banco
from analysis.signal_filter import filtrar_sinal

DB = Path("database/goalbot.db")

if not DB.exists():
    raise SystemExit("Banco de dados nao encontrado")

resultados = analisar_banco(db_path=DB, limite=500)
contagem = {"CANDIDATO": 0, "NAO_ENVIAR": 0}

with sqlite3.connect(DB) as con:
    for evento, minuto, analise in resultados:
        registros = con.execute("""
            SELECT status, minuto
            FROM observacoes_live
            WHERE id_evento = ?
            ORDER BY id DESC
            LIMIT 2
        """, (evento,)).fetchall()

        if len(registros) < 2:
            continue

        status, minuto_atual = registros[0]
        status_anterior, _ = registros[1]

        if status != status_anterior:
            print(evento, "| IGNORADO: mudanca de periodo")
            continue

        resultado = filtrar_sinal(
            status, minuto_atual, analise
        )

        decisao = resultado["decisao"]
        contagem[decisao] += 1

        print(
            evento,
            "|", minuto_atual,
            "|", analise.get("classificacao"),
            "|", decisao
        )

print("\nRESUMO:", contagem)
print("MODO TESTE: nenhum sinal enviado")
