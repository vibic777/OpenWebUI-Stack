#!/usr/bin/env bash
# images-load.sh — run on the AIR-GAPPED host: docker load tar files made by images-save.sh.
# Запускать на сервере БЕЗ интернета: загрузить образы из tar.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "images-load.sh — load saved images into local Docker (no internet)." \
    "images-load.sh — загрузить сохранённые образы в локальный Docker (без интернета)."
  cat <<'HELP'
Использование:
  ./images-load.sh --from DIR [--check]

  --from DIR   directory with *.tar (made by images-save.sh)
  --check      only verify SHA256SUMS and report which images of this stack are still missing

After load: ./deploy-stack.sh --offline   (new host)   or   ./update-stack.sh --offline   (new versions)
HELP
}
FROM=""; CHECK=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --from) FROM="$2"; shift 2 ;;
    --check) CHECK=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
[[ -d "$FROM" ]] || ops_die "--from DIR required"
if [[ -f "$FROM/SHA256SUMS" ]]; then ( cd "$FROM" && sha256sum -c SHA256SUMS ) || ops_die "checksum mismatch"; fi
if [[ $CHECK -eq 0 ]]; then
  for t in "$FROM"/*.tar; do ops_info "load $t"; docker load -i "$t"; done
fi
if [[ -f "$HERE/.env" ]]; then
  miss="$(ops_missing_images "$(ops_compose)" "$HERE")"
  if [[ -n "$miss" ]]; then echo "STILL MISSING / ещё нет:"; echo "$miss"; exit 1; fi
  ops_info "all images of this stack are present"
else
  ops_info "no .env yet: image completeness not checked (run ./deploy-stack.sh --init first)"
fi
