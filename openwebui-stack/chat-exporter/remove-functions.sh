#!/usr/bin/env bash
SCRIPT_VERSION="1.0.2"
for version_arg in "$@"; do
  case "$version_arg" in --version|-V) printf '%s %s\n' "$(basename "$0")" "$SCRIPT_VERSION"; exit 0;; esac
done
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONT="open-webui"
EMAIL="${OWUI_ADMIN_EMAIL:-}"
URL="${OWUI_URL:-http://127.0.0.1:8080}"
REMOVE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) [[ $# -ge 2 ]] || { echo "Использование: $0 --all [--url URL] --email EMAIL [--container NAME]" >&2; exit 2; }; EMAIL="$2"; shift 2 ;;
    --container) [[ $# -ge 2 ]] || { echo "Использование: $0 --all [--url URL] [--email EMAIL] [--container NAME]" >&2; exit 2; }; CONT="$2"; shift 2 ;;
    --url) [[ $# -ge 2 ]] || { echo "Использование: $0 --all [--url URL] [--email EMAIL] [--container NAME]" >&2; exit 2; }; URL="$2"; shift 2 ;;
    --all) REMOVE=1; shift ;;
    -h|--help) cat <<'HELP'
chat-exporter/remove-functions.sh — удалить только Function export_entire_chat.
--all обязателен; --url URL (OWUI_URL или http://127.0.0.1:8080), --email EMAIL
(OWUI_ADMIN_EMAIL или запрос), --container NAME (open-webui), --version/-V, -h/--help.
Пароль запрашивается скрыто; данные чатов при удалении Function не меняются.

Примеры:
  ./remove-functions.sh --all --email admin@example.org
  ./remove-functions.sh --all --url http://127.0.0.1:8080
HELP
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ "$REMOVE" -eq 1 ]] || { echo 'ERROR: specify --all to remove export_entire_chat' >&2; exit 2; }
[[ -n "$EMAIL" ]] || { [[ -r /dev/tty ]] || { echo 'ERROR: pass --email ADMIN_EMAIL without a terminal' >&2; exit 1; }; read -r -p 'Open WebUI admin e-mail: ' EMAIL </dev/tty; }
docker inspect -f '{{.State.Running}}' "$CONT" | grep -q true || { echo "Container $CONT is not running" >&2; exit 1; }
[[ -r /dev/tty ]] || { echo 'ERROR: no terminal to read password' >&2; exit 1; }
read -r -s -p "Password for $EMAIL: " PASS </dev/tty
echo >/dev/tty
[[ -n "$PASS" ]] || { echo 'ERROR: admin password is empty' >&2; exit 1; }
API_URL="$URL"
case "${URL%/}" in http://127.0.0.1:8080|http://localhost:3000) API_URL=http://127.0.0.1:8080;; esac
TMPD="/tmp/owui-chat-export-remove-$$"
trap 'docker exec "$CONT" rm -rf "$TMPD" >/dev/null 2>&1 || true' EXIT
docker exec "$CONT" mkdir -p "$TMPD"
docker cp "$HERE/functions/install_functions.py" "$CONT:$TMPD/"
echo "Removing whole-chat exporter via $CONT (API $API_URL)..."
docker exec -e OWUI_ADMIN_PASSWORD="$PASS" "$CONT" python3 "$TMPD/install_functions.py" --url "$API_URL" --email "$EMAIL" --dir "$TMPD" --remove export_entire_chat
