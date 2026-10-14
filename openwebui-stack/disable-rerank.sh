#!/usr/bin/env bash
# Disable reranker; keep GGUF and volumes. Safe for A/B off.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
disable-rerank.sh — остановить reranker и снять его Compose overlay с Open WebUI.
Загруженная модель и Docker-образы не удаляются; данные основного стека сохраняются.

Аргументы: не принимает параметры, кроме -h/--help.
Перед отключением можно проверить слой: ./check-rerank.sh.

Примеры:
  ./disable-rerank.sh
  ./check-rerank.sh && ./disable-rerank.sh
HELP
  exit 0
fi
(( $# == 0 )) || { echo "Аргументы не поддерживаются; используйте --help" >&2; exit 2; }
docker compose -f docker-compose.yml -f docker-compose.no-rerank.yml up -d
docker compose -f docker-compose.rerank.yml down
rm -f .rerank-enabled
echo "Rerank OFF (open-webui recreated without external reranker)."
