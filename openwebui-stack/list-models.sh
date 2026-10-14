#!/usr/bin/env bash
# Получить список моделей, видимых текущему пользователю Open WebUI через API.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
usage() {
  cat <<'HELP'
Использование:
  ./list-models.sh [-h|--help]

Получает список моделей через API текущего Open WebUI. Нужен API-ключ
администратора: OPENWEBUI_API_KEY или файл с ключом OPENWEBUI_API_KEY_FILE.
WEBUI_URL берётся из .env. Выведите список, выберите ID чат-модели и задайте
OPENWEBUI_E2E_MODEL перед ./full-test.sh --e2e-rag.
Ключ провайдера модели вводить не нужно: его использует Open WebUI.
HELP
}
for arg in "$@"; do case "$arg" in -h|--help) usage; exit 0 ;; *) ops_die "неизвестный аргумент: $arg" ;; esac; done
ENVF="$HERE/.env"
API_KEY="${OPENWEBUI_API_KEY:-${WEBUI_API_KEY:-}}"
[[ -n "$API_KEY" ]] || API_KEY="$(ops_env_get "$ENVF" OPENWEBUI_API_KEY)"
if [[ -z "$API_KEY" ]]; then
  KEY_FILE="${OPENWEBUI_API_KEY_FILE:-$(ops_env_get "$ENVF" OPENWEBUI_API_KEY_FILE)}"
  if [[ -n "$KEY_FILE" ]]; then
    [[ -r "$KEY_FILE" ]] || ops_die "файл API-ключа не читается: $KEY_FILE"
    API_KEY="$(tr -d '\r\n' < "$KEY_FILE")"
  fi
fi
[[ -n "$API_KEY" ]] || ops_die "задайте OPENWEBUI_API_KEY или OPENWEBUI_API_KEY_FILE (см. RAG-E2E-HELP.md)"
BASE_URL="$(ops_env_get "$ENVF" WEBUI_URL)"
[[ -n "$BASE_URL" && "$BASE_URL" != https://CHANGE-ME-HOST ]] || ops_die "задайте WEBUI_URL в $ENVF"
export OPENWEBUI_API_KEY="$API_KEY" OPENWEBUI_BASE_URL="${BASE_URL%/}"
python3 - <<'PY'
import json, os, sys, urllib.error, urllib.request
url = os.environ['OPENWEBUI_BASE_URL'] + '/api/models'
req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + os.environ['OPENWEBUI_API_KEY'], 'Accept': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
        ctype = response.headers.get('Content-Type', '')
        if 'json' not in ctype.lower():
            preview = raw[:240].decode('utf-8', 'replace').replace('\n', ' ')
            raise RuntimeError(f'API вернул не JSON (Content-Type={ctype}); проверьте WEBUI_URL, прокси и путь /api/models; ответ начинается с {preview!r}')
        result = json.loads(raw)
except urllib.error.HTTPError as exc:
    preview = exc.read(240).decode('utf-8', 'replace').replace('\n', ' ')
    raise SystemExit(f'ОШИБКА: HTTP {exc.code} при запросе {url}; проверьте API-ключ/права и WEBUI_URL. Ответ: {preview}')
except Exception as exc:
    raise SystemExit(f'ОШИБКА: {exc}')
models = result.get('data', result.get('models', [])) if isinstance(result, dict) else result
if not isinstance(models, list):
    raise SystemExit('ОШИБКА: неожиданная структура ответа /api/models')
print(f'Доступные модели ({len(models)}):')
for item in models:
    if isinstance(item, dict):
        mid = item.get('id') or item.get('name') or '(без ID)'
        label = item.get('name')
        print(f"- {mid}" + (f" — {label}" if label and label != mid else ''))
    else:
        print(f'- {item}')
PY
