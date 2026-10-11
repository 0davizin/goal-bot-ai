from datetime import datetime, timezone

STATUS_VALIDOS = {
    "STATUS_FIRST_HALF",
    "STATUS_SECOND_HALF",
}

def verificar_live(registros, agora=None):
    if len(registros) < 2:
        return False, "Menos de duas observacoes"

    atual, anterior = registros[0], registros[1]

    if atual["status"] not in STATUS_VALIDOS:
        return False, "Partida fora do tempo regulamentar"

    if atual["status"] != anterior["status"]:
        return False, "Mudanca de periodo"

    try:
        t1 = datetime.fromisoformat(atual["coletado_em_utc"])
        t0 = datetime.fromisoformat(anterior["coletado_em_utc"])

        if t1.tzinfo is None or t0.tzinfo is None:
            return False, "Horario sem fuso"

        agora = agora or datetime.now(timezone.utc)

        idade = (agora - t1).total_seconds()
        intervalo = (t1 - t0).total_seconds()

        if idade < -30 or idade > 300:
            return False, "Dados antigos ou horario inconsistente"

        if intervalo <= 0 or intervalo > 600:
            return False, "Intervalo de coleta invalido"

    except (ValueError, TypeError, KeyError):
        return False, "Horario invalido"

    return True, "Observacoes recentes e consistentes"
