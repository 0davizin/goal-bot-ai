"""Correção conservadora do GOAL BOT AI: separa falta de dados de MONITORAR.
Execute na raiz ~/goal-bot-ai. Não altera banco, monitor nem Telegram.
"""
from pathlib import Path
import ast
import shutil

path = Path('analysis/goal_engine.py')
if not path.is_file():
    raise SystemExit('ERRO: execute na raiz ~/goal-bot-ai')
original = path.read_text(encoding='utf-8')
source = ast.parse(original)
fn = next((n for n in source.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'avaliar_jogo'), None)
if fn is None:
    raise SystemExit('ERRO: funcao avaliar_jogo nao encontrada. Nada alterado.')

# Altera somente retornos antecipados cuja justificativa indica insuficiência de dados.
reasons = {
    'Menos de duas observações',
    'Minutos insuficientes ou inconsistentes',
    'Intervalo superior a 10 minutos',
    'Estatísticas essenciais ausentes',
    'Contadores retrocederam; possível correção da fonte',
}
lines = original.splitlines(keepends=True)
changes = []
for node in ast.walk(fn):
    if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
        continue
    values = {}
    for key, val in zip(node.value.keys, node.value.values):
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(val, ast.Constant):
            values[key.value] = val.value
    if values.get('classificacao') != 'MONITORAR' or values.get('motivo') not in reasons:
        continue
    for key, val in zip(node.value.keys, node.value.values):
        if isinstance(key, ast.Constant) and key.value == 'classificacao' and isinstance(val, ast.Constant):
            line_i = val.lineno - 1
            old_line = lines[line_i]
            a, b = val.col_offset, val.end_col_offset
            token = old_line[a:b]
            if token not in ("'MONITORAR'", '"MONITORAR"'):
                raise SystemExit('ERRO: formato inesperado; nenhuma alteracao feita.')
            changes.append((line_i, a, b, token[0] + 'DADOS_INSUFICIENTES' + token[0]))
if len(changes) != 5:
    raise SystemExit(f'ERRO: esperadas 5 correcoes, encontradas {len(changes)}. Nada alterado.')
for i, a, b, replacement in sorted(changes, reverse=True):
    lines[i] = lines[i][:a] + replacement + lines[i][b:]
updated = ''.join(lines)
compile(updated, str(path), 'exec')
backup = path.with_name('goal_engine_pre_correcao.py')
if backup.exists():
    raise SystemExit(f'ERRO: backup {backup} ja existe; nada alterado.')
shutil.copy2(path, backup)
path.write_text(updated, encoding='utf-8')
print('OK: 5 retornos corrigidos para DADOS_INSUFICIENTES')
print(f'Backup adicional: {backup}')
print('Limiares BOA/FORTE e outras funcoes preservados; Telegram nao alterado.')
