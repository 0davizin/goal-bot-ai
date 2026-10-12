"""Telegram: envio, edição e comandos de relatórios GOAL BOT AI."""
from pathlib import Path
import os
import logging
import threading
import time
import requests

ENV = Path(__file__).resolve().parents[1] / '.env'

def carregar_config():
    config = {}
    if ENV.exists():
        for linha in ENV.read_text(encoding='utf-8').splitlines():
            linha = linha.strip()
            if not linha or linha.startswith('#') or '=' not in linha:
                continue
            chave, valor = linha.split('=', 1)
            config[chave.strip()] = valor.strip().strip('"').strip("'")
    config.update({k: v for k, v in os.environ.items() if k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_ADMIN_USER_ID')})
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
        raise RuntimeError(f"Telegram recusou {metodo}: {dados.get('description', 'Erro desconhecido')}")
    return dados['result']

def enviar_mensagem(texto):
    resultado = _chamar_telegram('sendMessage', {'text': texto})
    return resultado['message_id']

def editar_mensagem(message_id, texto):
    if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
        raise ValueError('message_id inválido')
    return _chamar_telegram('editMessageText', {'message_id': message_id, 'text': texto, 'parse_mode': 'HTML'})

def _comandos_loop(db):
    from goalbot_resultados import relatorio_status, inicializar
    config = carregar_config()
    token = config.get('TELEGRAM_BOT_TOKEN')
    chat_id = str(config.get('TELEGRAM_CHAT_ID', ''))
    admin_id = str(config.get('TELEGRAM_ADMIN_USER_ID', ''))
    if not token or not chat_id:
        logging.warning('Comandos Telegram desativados: credenciais ausentes')
        return
    url = f'https://api.telegram.org/bot{token}/getUpdates'
    offset = None
    inicializar(db)
    while True:
        try:
            # Na primeira consulta, descartar atualizações antigas sem responder a comandos obsoletos.
            if offset is None:
                r = requests.get(url, params={'offset': -1, 'timeout': 0, 'allowed_updates': '["message"]'}, timeout=15)
                r.raise_for_status()
                payload = r.json()
                if not payload.get('ok'):
                    raise RuntimeError(payload.get('description', 'getUpdates falhou'))
                itens = payload.get('result', [])
                offset = (max(item['update_id'] for item in itens) + 1) if itens else 0
                continue
            r = requests.get(url, params={'offset': offset, 'timeout': 20, 'allowed_updates': '["message"]'}, timeout=30)
            r.raise_for_status()
            payload = r.json()
            if not payload.get('ok'):
                raise RuntimeError(payload.get('description', 'getUpdates falhou'))
            for item in payload.get('result', []):
                offset = max(offset, item['update_id'] + 1)
                mensagem = item.get('message') or {}
                origem = mensagem.get('chat') or {}
                if str(origem.get('id')) != chat_id:
                    continue
                if admin_id and str((mensagem.get('from') or {}).get('id')) != admin_id:
                    continue
                comando = str(mensagem.get('text') or '').split(maxsplit=1)[0].split('@')[0].lower()
                periodo = {'/status': 'dia', '/mensal': 'mes', '/geral': 'geral'}.get(comando)
                if periodo:
                    try:
                        texto = relatorio_status(db, periodo)
                        _chamar_telegram('sendMessage', {'text': texto, 'reply_to_message_id': mensagem['message_id']})
                    except Exception:
                        logging.exception('Falha ao responder %s', comando)
        except Exception:
            logging.exception('Erro ao consultar comandos Telegram; nova tentativa em 10 segundos')
            time.sleep(10)

def iniciar_comandos(db):
    thread = threading.Thread(target=_comandos_loop, args=(db,), daemon=True, name='telegram-comandos')
    thread.start()
    return thread
