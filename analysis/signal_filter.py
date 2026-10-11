from analysis.period_filter import avaliar_periodo


def filtrar_sinal(status, minuto, analise):
    periodo = avaliar_periodo(status, minuto)

    if periodo["decisao"] != "PERMITIDO":
        return {
            "decisao": "NAO_ENVIAR",
            "motivo": periodo["motivo"]
        }

    if analise.get("classificacao") not in ("BOA", "FORTE"):
        return {
            "decisao": "NAO_ENVIAR",
            "motivo": "Pressao ofensiva insuficiente"
        }

    return {
        "decisao": "CANDIDATO",
        "classificacao": analise["classificacao"],
        "motivo": "Pressao ofensiva identificada"
    }


if __name__ == "__main__":
    testes = [
        ("STATUS_FIRST_HALF", "20'", {"classificacao": "FORTE"}),
        ("STATUS_SECOND_HALF", "67'", {"classificacao": "BOA"}),
        ("STATUS_SECOND_HALF", "85'", {"classificacao": "FORTE"}),
        ("STATUS_SECOND_HALF", "90'+4'", {"classificacao": "FORTE"}),
        ("STATUS_FIRST_HALF", "25'", {"classificacao": "EVITAR"}),
    ]

    for status, minuto, analise in testes:
        print(minuto, filtrar_sinal(status, minuto, analise))
