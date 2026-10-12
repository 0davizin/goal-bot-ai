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

# Serializa envios e edições entre o monitor e a thread de comandos.
# O limite real varia conforme o chat e a API; 1,2 s é um espaçamento prudente.
_TELEGRAM_LOCK = threading.Lock()
_ULTIMA_REQUISICAO = 0.0
_INTERVALO_MINIMO = 1.2


def _chamar_telegram(metodo, payload):
    global _ULTIMA_REQUISICAO
    config = carregar_config()
    token = config['TELEGRAM_BOT_TOKEN']
    url = f'https://api.telegram.org/bot{token}/{metodo}'
    with _TELEGRAM_LOCK:
        for tentativa in range(4):
            espera = _INTERVALO_MINIMO - (time.monotonic() - _ULTIMA_REQUISICAO)
            if espera > 0:
                time.sleep(espera)
            _ULTIMA_REQUISICAO = time.monotonic()
            try:
                resposta = requests.post(
                    url,
                    json={'chat_id': config['TELEGRAM_CHAT_ID'], **payload},
                    timeout=15,
                )
            except requests.RequestException as exc:
                # Nunca registrar a URL da API: ela contém o token do bot.
                raise RuntimeError(f'Falha de rede no Telegram ({metodo}): {type(exc).__name__}') from None
            try:
                dados = resposta.json()
            except ValueError:
                dados = {}
            if resposta.status_code == 429 or dados.get('error_code') == 429:
                parametros = dados.get('parameters') or {}
                try:
                    retry_after = max(1, min(120, int(parametros.get('retry_after', 5))))
                except (TypeError, ValueError):
                    retry_after = 5
                if tentativa == 3:
                    raise RuntimeError(f'Telegram 429 em {metodo}; novas tentativas na próxima rodada')
                logging.warning('Telegram 429 em %s; aguardando %ss antes de repetir', metodo, retry_after)
                time.sleep(retry_after + 1)
                continue
            if resposta.status_code >= 400 or not dados.get('ok'):
                descricao = str(dados.get('description', 'erro não detalhado'))
                if metodo == 'editMessageText' and 'message is not modified' in descricao.lower():
                    return True
                raise RuntimeError(f'Telegram recusou {metodo}: HTTP {resposta.status_code} ({descricao})')
            return dados['result']
    raise RuntimeError(f'Falha inesperada na API do Telegram ({metodo})')

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
                
                if r.status_code >= 400:
                    raise RuntimeError(f'Telegram getUpdates HTTP {r.status_code}')
                payload = r.json()
                if not payload.get('ok'):
                    raise RuntimeError(payload.get('description', 'getUpdates falhou'))
                itens = payload.get('result', [])
                offset = (max(item['update_id'] for item in itens) + 1) if itens else 0
                continue
            r = requests.get(url, params={'offset': offset, 'timeout': 20, 'allowed_updates': '["message"]'}, timeout=30)
            if r.status_code >= 400:
                raise RuntimeError(f'Telegram getUpdates HTTP {r.status_code}')
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
