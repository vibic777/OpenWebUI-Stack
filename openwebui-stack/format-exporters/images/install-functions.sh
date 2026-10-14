#!/usr/bin/env bash
SCRIPT_VERSION="2026.09.26.8"
for version_arg in "$@"; do
  case "$version_arg" in --version|-V) printf '%s %s\n' "$(basename "$0")" "$SCRIPT_VERSION"; exit 0;; esac
done
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FDIR="$HERE/functions"; CONT="open-webui"; EMAIL="${OWUI_ADMIN_EMAIL:-}"; URL="${OWUI_URL:-http://127.0.0.1:8080}"; API_URL="$URL"
while [[ $# -gt 0 ]]; do case "$1" in
  --email) EMAIL="$2"; shift 2;; --container) CONT="$2"; shift 2;; --url) URL="$2"; shift 2;;
  -h|--help) echo "Usage: $0 [--url URL] [--email ADMIN_EMAIL] [--container open-webui]"; exit 0;;
  *) echo "Unknown option: $1" >&2; exit 2;; esac; done
docker inspect -f '{{.State.Running}}' "$CONT" | grep -q true || { echo "ERROR: container $CONT is not running" >&2; exit 1; }
if [[ -z "$EMAIL" ]]; then [[ -r /dev/tty ]] || { echo "ERROR: no terminal; pass --email ADMIN_EMAIL" >&2; exit 1; }; read -r -p 'Open WebUI admin e-mail: ' EMAIL </dev/tty; fi
[[ -n "$EMAIL" ]] || { echo "ERROR: admin e-mail is empty" >&2; exit 1; }
[[ -r /dev/tty ]] || { echo "ERROR: no terminal to read password" >&2; exit 1; }
read -r -s -p "Password for $EMAIL: " PASS </dev/tty; echo >/dev/tty
[[ -n "$PASS" ]] || { echo "ERROR: password is empty" >&2; exit 1; }
case "${URL%/}" in http://127.0.0.1:8080|http://localhost:3000) API_URL="http://127.0.0.1:8080";; esac
echo "Installing export_images_menu through container $CONT (API $API_URL)..."
TMPD="/tmp/owui-export_images_menu-$$"; trap 'docker exec "$CONT" rm -rf "$TMPD" >/dev/null 2>&1 || true' EXIT
docker exec "$CONT" mkdir -p "$TMPD"
docker cp "$FDIR/export_action.py" "$CONT:$TMPD/"
docker cp "$FDIR/install_functions.py" "$CONT:$TMPD/"
printf '%s\n' "$PASS" | docker exec -i "$CONT" python3 "$TMPD/install_functions.py" --url "$API_URL" --email "$EMAIL" --dir "$TMPD" --password-stdin
