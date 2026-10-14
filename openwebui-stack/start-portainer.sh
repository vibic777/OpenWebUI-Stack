#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "start-portainer.sh — Start Portainer (docker compose) separately from the main stack." \
    "start-portainer.sh — Запустить Portainer (docker compose) отдельно от основного стека."
  cat <<'HELP'
Использование:
  ./start-portainer.sh [-h|--help]

Options / Параметры:
  -h, --help                 Показать эту справку
  --dry-run                  Print command only

Examples / Примеры:
  ./start-portainer.sh
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
COMPOSE="$DIR/docker-compose.portainer.yml"
[[ -f "$COMPOSE" ]] || ops_die "missing $COMPOSE"
DC="$(ops_compose "$DIR")"
ops_info "start portainer compose=$COMPOSE"
cd "$DIR"
CMD=($DC -f docker-compose.portainer.yml up -d)
if [[ "$DRY" -eq 1 ]]; then echo "DRY-RUN: ${CMD[*]}"; exit 0; fi
"${CMD[@]}"
ops_info "portainer started"
