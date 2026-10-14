#!/usr/bin/env bash
SCRIPT_VERSION="2026.09.25.1"
for version_arg in "$@"; do
  case "$version_arg" in --version|-V) printf '%s %s\n' "$(basename "$0")" "$SCRIPT_VERSION"; exit 0;; esac
done
# install-functions.sh — install/update Open WebUI Functions (plugins) on THIS server, through the Open WebUI API.
# Thin wrapper: copies functions/*.py + functions/install_functions.py into the open-webui container and runs the
# standalone installer there (no host python needed). From another machine use functions/install_functions.py directly.
set -euo pipefail

usage() {
  cat <<'HELP'
install-functions.sh — install / update Open WebUI Functions (plugins) from functions/*.py
install-functions.sh — установить / обновить плагины Open WebUI из functions/*.py (без интернета)

Использование:
  ./install-functions.sh [--url URL] [--email ADMIN_EMAIL] [--ask-password] [--file FILE]... [--no-global] [--list] [--remove ID] [--container NAME] [-h]

  --email E         Open WebUI ADMIN e-mail (or $OWUI_ADMIN_EMAIL; asked if missing)
  --ask-password    ask the admin password (or $OWUI_ADMIN_PASSWORD). Never pass it as an argument (visible in `ps`).
  --file F          install only this file (repeatable; default: every functions/*.py)
  --no-global       enable but do not make Global
  --list            show installed functions and exit
  --remove ID       delete function ID (e.g. export_office) and exit (see also remove-functions.sh)
  --remove-bundled  delete every plugin of this bundle and exit
  --container NAME  open-webui container (default: open-webui)
  --url URL        API base URL (default http://127.0.0.1:8080; or $OWUI_URL)

Other ways / Другие способы (любой):
  * from ANY computer:   python functions/install_functions.py --url https://<host> --email <admin> [--insecure]
  * manual:              Admin -> Functions -> "+" -> paste functions/export_office.py -> Save -> Active + Global
  * import:              Admin -> Functions -> Import -> functions/functions.json
  * portable bundle:     owui-plugins-<version>.zip (built by functions/build_bundle.py or build-release)
HELP
}
die() { echo "ERROR: $*" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; FDIR="$HERE/functions"
EMAIL="${OWUI_ADMIN_EMAIL:-}"; ASK=0; CONT=open-webui; URL="${OWUI_URL:-http://127.0.0.1:8080}"; ARGS=(); FILES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --ask-password) ASK=1; shift ;;
    --file) FILES+=("$2"); shift 2 ;;
    --no-global) ARGS+=(--no-global); shift ;;
    --list) ARGS+=(--list); shift ;;
    --remove) ARGS+=(--remove "$2"); shift 2 ;;
    --remove-bundled) ARGS+=(--remove-bundled); shift ;;
    --container) CONT="$2"; shift 2 ;;
    --url) URL="$2"; shift 2 ;;
    *) die "unknown arg: $1 (try --help)" ;;
  esac
done
docker inspect -f '{{.State.Running}}' "$CONT" 2>/dev/null | grep -q true || die "container $CONT is not running"
[[ -f "$FDIR/install_functions.py" ]] || die "missing $FDIR/install_functions.py"
[[ -n "$EMAIL" ]] || { [[ -r /dev/tty ]] || die "pass --email ADMIN_EMAIL when no terminal is available"; read -r -p "Open WebUI admin e-mail: " EMAIL </dev/tty; }
PASS="${OWUI_ADMIN_PASSWORD:-}"
if [[ -z "$PASS" || $ASK -eq 1 ]]; then [[ -r /dev/tty ]] || die "no terminal to read password; set OWUI_ADMIN_PASSWORD or use an interactive terminal"; read -r -s -p "Password for $EMAIL: " PASS </dev/tty; echo >/dev/tty; fi
[[ -n "$PASS" ]] || die "admin password is empty"
API_URL="$URL"
case "${URL%/}" in http://127.0.0.1:8080|http://localhost:3000) API_URL="http://127.0.0.1:8080";; esac

TMPD="/tmp/owui-plugins-$$"
trap 'docker exec "$CONT" rm -rf "$TMPD" >/dev/null 2>&1 || true' EXIT
docker exec "$CONT" mkdir -p "$TMPD"
if [[ ${#FILES[@]} -gt 0 ]]; then
  for f in "${FILES[@]}"; do [[ -f "$f" ]] || die "no such file: $f"; docker cp "$f" "$CONT:$TMPD/$(basename "$f")"; done
else
  shopt -s nullglob
  for f in "$FDIR"/*.py; do case "$(basename "$f")" in build_bundle.py) ;; *) docker cp "$f" "$CONT:$TMPD/" ;; esac; done
fi
echo "Running Function installer in container $CONT (API $API_URL)..."
docker exec -e OWUI_ADMIN_PASSWORD="$PASS" "$CONT" python3 "$TMPD/install_functions.py" \
  --url "$API_URL" --email "$EMAIL" --dir "$TMPD" "${ARGS[@]}"
