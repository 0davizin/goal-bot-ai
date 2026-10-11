"""Envio e edição de sinais no Telegram para o GOAL BOT AI."""
from pathlib import Path
import requests

ENV = Path(__file__).resolve().parents[1] / '.env'


def carregar_config():
    config = {}
    for linha in ENV.read_text(encoding='utf-8').splitlines():
        linha = linha.strip()
        if not linha or linha.startswith('#') or '=' not in linha:
            continue
        chave, valor = linha.split('=', 1)
        config[chave.strip()] = valor.strip().strip('"').strip("'")
    return config


def _chamar_telegram(metodo, payload):
    config = carregar_config()
    token = config['TELEGRAM_BOT_TOKEN']
    resposta = requests.post(
        f'https://api.telegram.org/bot{token}/{metodo}',
        json={'chat_id': config['TELEGRAM_CHAT_ID'], **payload},
        timeout=15,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    if not dados.get('ok'):
        raise RuntimeError(
            f"Telegram recusou {metodo}: {dados.get('description', 'Erro desconhecido')}"
        )
    return dados['result']


def enviar_mensagem(texto):
    """Envia o sinal e retorna o message_id da mensagem criada."""
    resultado = _chamar_telegram('sendMessage', {'text': texto})
    return resultado['message_id']


def editar_mensagem(message_id, texto):
    """Atualiza o texto de uma mensagem já enviada pelo bot."""
    if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
        raise ValueError('message_id inválido')
    return _chamar_telegram(
        'editMessageText',
        {'message_id': message_id, 'text': texto, 'parse_mode': 'HTML'},
    )
