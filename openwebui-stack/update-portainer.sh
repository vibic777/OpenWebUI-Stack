#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "update-portainer.sh — Pull new Portainer image and recreate the compose service." \
    "update-portainer.sh — Скачать новый образ Portainer и пересоздать сервис."
  cat <<'HELP'
Использование:
  ./update-portainer.sh [-y|--yes] [--dry-run] [-h|--help]

Options / Параметры:
  -h, --help                 Показать эту справку
  -y, --yes                  Do not ask for confirmation
  --dry-run                  Print commands only

Examples / Примеры:
  ./update-portainer.sh --yes
HELP
}

TARGET="$(basename "$HERE")"; DRY=0; YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -y|--yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
DIR="$HERE"
COMPOSE="$DIR/docker-compose.portainer.yml"
[[ -f "$COMPOSE" ]] || ops_die "missing $COMPOSE"
DC="$(ops_compose "$DIR")"
ops_info "update portainer compose=$COMPOSE"
cd "$DIR"
if [[ "$YES" -ne 1 && "$DRY" -ne 1 ]]; then
  read -r -p "Pull Portainer image and recreate? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" || "$ans" == "yes" ]] || ops_die "cancelled"
fi
if [[ "$DRY" -eq 1 ]]; then
  echo "DRY-RUN: $DC -f docker-compose.portainer.yml pull"
  echo "DRY-RUN: $DC -f docker-compose.portainer.yml up -d"
  exit 0
fi
$DC -f docker-compose.portainer.yml pull
$DC -f docker-compose.portainer.yml up -d
ops_info "portainer updated"
