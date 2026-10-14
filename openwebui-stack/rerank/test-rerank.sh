#!/usr/bin/env bash
# Run the probe from inside Open WebUI — rerank has no host port.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
rerank/test-rerank.sh — отправить тестовый запрос к включённому reranker из Open WebUI.
Проверка не переключает слой и не меняет настройки.

Аргументы: не принимает параметры, кроме -h/--help.
Требования: reranker запущен и настроен; если слой выключен, используйте check-rerank.sh.

Примеры:
  ./rerank/test-rerank.sh
  cd /path/to/openwebui-stack && ./rerank/test-rerank.sh
HELP
  exit 0
fi
(( $# == 0 )) || { echo "Аргументы не поддерживаются; используйте --help" >&2; exit 2; }
exec docker exec -i open-webui python - < "$DIR/test-rerank.py"
