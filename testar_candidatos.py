import sqlite3

from analysis.goal_engine import analisar_banco
from analysis.live_guard import verificar_live
from analysis.signal_filter import filtrar_sinal

DB = "database/goalbot.db"

resultados = analisar_banco(db_path=DB, limite=500)
resumo = {
    "CANDIDATO": 0,
    "NAO_ENVIAR": 0,
    "BLOQUEADO_LIVE": 0,
}

with sqlite3.connect(DB) as con:
    con.row_factory = sqlite3.Row

    for evento, minuto, analise in resultados:
        registros = con.execute("""
            SELECT status, minuto, coletado_em_utc
            FROM observacoes_live
            WHERE id_evento = ?
            ORDER BY id DESC
            LIMIT 2
        """, (evento,)).fetchall()

        valido, motivo = verificar_live(registros)

        if not valido:
            resumo["BLOQUEADO_LIVE"] += 1
            continue

        status = registros[0]["status"]
        minuto_atual = registros[0]["minuto"]

        decisao = filtrar_sinal(
            status, minuto_atual, analise
        )

        classe = analise.get("classificacao")
        resultado = decisao["decisao"]
        resumo[resultado] += 1

        if resultado == "CANDIDATO":
            print(
                "CANDIDATO:",
                evento,
                minuto_atual,
                classe
            )

print("RESUMO FINAL:", resumo)
print("TELEGRAM DESATIVADO")
