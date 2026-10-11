import re


def avaliar_periodo(status, minuto):
    """Filtro experimental de janela operacional da partida."""

    if status not in (
        "STATUS_FIRST_HALF",
        "STATUS_SECOND_HALF",
    ):
        return {
            "decisao": "BLOQUEADO",
            "motivo": "Partida fora dos períodos permitidos",
        }

    texto = str(minuto).strip() if minuto is not None else ""
    partes = re.fullmatch(
        r"(\d+)\s*'?\s*(?:\+\s*(\d+)\s*'?)?",
        texto,
    )

    if not partes:
        return {
            "decisao": "BLOQUEADO",
            "motivo": "Minuto inválido ou indisponível",
        }

    base = int(partes.group(1))
    acrescimo = int(partes.group(2) or 0)
    tempo = base + acrescimo

    if status == "STATUS_FIRST_HALF":
        if base > 45 or acrescimo > 0:
            return {
                "decisao": "MONITORAR",
                "motivo": "Acréscimos do primeiro tempo",
            }

        if 1 <= tempo <= 40:
            return {
                "decisao": "PERMITIDO",
                "motivo": "Janela operacional do primeiro tempo",
            }

        return {
            "decisao": "MONITORAR",
            "motivo": "Fora da janela principal do primeiro tempo",
        }

    if base >= 90 or acrescimo > 0:
        return {
            "decisao": "BLOQUEADO",
            "motivo": "Final da partida ou acréscimos",
        }

    if 46 <= tempo <= 80:
        return {
            "decisao": "PERMITIDO",
            "motivo": "Janela operacional do segundo tempo",
        }

    return {
        "decisao": "MONITORAR",
        "motivo": "Fora da janela principal do segundo tempo",
    }


if __name__ == "__main__":
    testes = [
        ("STATUS_FIRST_HALF", "10'"),
        ("STATUS_FIRST_HALF", "40'"),
        ("STATUS_FIRST_HALF", "45'+2'"),
        ("STATUS_SECOND_HALF", "62'"),
        ("STATUS_SECOND_HALF", "85'"),
        ("STATUS_SECOND_HALF", "90'+4'"),
        ("STATUS_FULL_TIME", "90'"),
    ]

    for status, minuto in testes:
        resultado = avaliar_periodo(status, minuto)
        print(status, minuto, "=>", resultado)
