#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "update-stack.sh — Pull new images and recreate the Open WebUI stack." \
    "update-stack.sh — Скачать новые образы и пересоздать стек Open WebUI."
  cat <<'HELP'
Использование:
  ./update-stack.sh [--offline] [-y|--yes] [--dry-run] [-h|--help]

Options / Параметры:
  -h, --help                 Показать эту справку
  --offline                  No internet: do NOT pull; use images loaded by ./images-load.sh
                             Без интернета: не качать, взять образы из ./images-load.sh
  -y, --yes                  Do not ask for confirmation / Без подтверждения
  --dry-run                  Print commands only

Examples / Примеры:
  ./update-stack.sh --yes
  ./images-load.sh --from /mnt/usb/images && ./update-stack.sh --offline --yes
  ./update-stack.sh --dry-run
HELP
}

TARGET="$(basename "$HERE")"; DRY=0; YES=0; OFFLINE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -y|--yes) YES=1; shift ;;
    --offline) OFFLINE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
DIR="$HERE"
DC="$(ops_compose "$DIR")"
FILES="$(ops_files "$DIR")"
ops_info "update stack target=$TARGET dir=$DIR"
cd "$DIR"
if [[ "$YES" -ne 1 && "$DRY" -ne 1 ]]; then
  read -r -p "Pull images and recreate $TARGET? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" || "$ans" == "yes" ]] || ops_die "cancelled"
fi
if [[ "$DRY" -eq 1 ]]; then
  [[ "$OFFLINE" -eq 1 ]] || echo "DRY-RUN: $DC $FILES --env-file .env pull"
  echo "DRY-RUN: $DC $FILES --env-file .env up -d$([[ $OFFLINE -eq 1 ]] && echo ' --pull never')"
  exit 0
fi
if [[ "$OFFLINE" -eq 1 ]]; then
  miss="$(ops_missing_images "$DC" "$DIR")"
  [[ -z "$miss" ]] || { echo "Missing images / Нет образов:"; echo "$miss"; ops_die "run ./images-load.sh --from DIR first"; }
  $DC $FILES --env-file .env up -d --pull never
else
  # Ignore individual pull failures only if every selected image is already local.
  $DC $FILES --env-file .env pull --ignore-pull-failures
  miss="$(ops_missing_images "$DC" "$DIR")"
  [[ -z "$miss" ]] || { echo "Missing images / Нет образов:"; echo "$miss"; ops_die "load/build missing images first"; }
  $DC $FILES --env-file .env up -d
fi
ops_info "updated $TARGET"
