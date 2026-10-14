#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "start-stack.sh — Start the Open WebUI docker compose stack." \
    "start-stack.sh — Запустить docker compose стек Open WebUI."
  cat <<'HELP'
Использование:
  ./start-stack.sh [-h|--help]

Options / Параметры:
  -h, --help                 Показать эту справку
  --dry-run                  Print command only

Examples / Примеры:
  ./start-stack.sh
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
ops_info "start stack target=$TARGET dir=$DIR"
cd "$DIR"
if ops_rerank_on "$DIR"; then
  ops_info "rerank enabled (marker .rerank-enabled): starting reranker first"
  [[ "$DRY" -eq 1 ]] || $DC -f docker-compose.rerank.yml --env-file .env up -d
fi
CMD=($DC $(ops_files "$DIR") --env-file .env up -d)
if [[ "$DRY" -eq 1 ]]; then echo "DRY-RUN: ${CMD[*]}"; exit 0; fi
"${CMD[@]}"
ops_info "started $TARGET"
