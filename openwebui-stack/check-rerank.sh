#!/usr/bin/env bash
# Functional external-reranker probe; optional when the rerank overlay is disabled.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
check-rerank.sh — проверить состояние интеграции reranker с Open WebUI.
Если слой выключен, команда сообщает SKIP; если включён — проверяет endpoint и ответ.

Аргументы: не принимает параметры, кроме -h/--help.
Требования: для проверки ответа слой должен быть включён через enable-rerank.sh.

Примеры:
  ./check-rerank.sh            # состояние и проба включённого слоя
  ./enable-rerank.sh && ./check-rerank.sh
HELP
  exit 0
fi
(( $# == 0 )) || ops_die "аргументы не поддерживаются; используйте --help"
if ! ops_rerank_on "$HERE"; then
  echo "SKIP  rerank is optional and currently disabled (.rerank-enabled is absent)"
  exit 0
fi
docker inspect -f '{{.State.Running}}' open-webui 2>/dev/null | grep -q true \
  || ops_die "open-webui is not running; start the Open WebUI Stack first"
exec bash "$HERE/rerank/test-rerank.sh"
