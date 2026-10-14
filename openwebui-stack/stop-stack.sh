#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "stop-stack.sh — Stop the Open WebUI docker compose stack." \
    "stop-stack.sh — Остановить docker compose стек Open WebUI."
  cat <<'HELP'
Использование:
  ./stop-stack.sh [-h|--help]

Options / Параметры:
  -h, --help                 Показать эту справку
  --dry-run                  Print command only / Только показать команду

Examples / Примеры:
  ./stop-stack.sh
  ./stop-stack.sh --dry-run
HELP
}

TARGET="$(basename "$HERE")"; DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --dry-run) DRY=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
DIR="$HERE"
DC="$(ops_compose "$DIR")"
ops_info "stop stack target=$TARGET dir=$DIR"
cd "$DIR"
CMD=($DC $(ops_files "$DIR") --env-file .env down)
if [[ "$DRY" -eq 1 ]]; then echo "DRY-RUN: ${CMD[*]}"; exit 0; fi
"${CMD[@]}"
if ops_rerank_on "$DIR"; then $DC -f docker-compose.rerank.yml --env-file .env down; fi
ops_info "stopped $TARGET (volumes are kept)"
