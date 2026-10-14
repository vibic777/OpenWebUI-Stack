#!/usr/bin/env bash
SCRIPT_VERSION="2026.10.11.3"
for version_arg in "$@"; do
  case "$version_arg" in --version|-V) printf '%s %s\n' "$(basename "$0")" "$SCRIPT_VERSION"; exit 0;; esac
done
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONT="open-webui"
EMAIL="${OWUI_ADMIN_EMAIL:-}"
URL="${OWUI_URL:-http://127.0.0.1:8080}"
API_URL="$URL"
PLUGIN_GROUPS=()
usage() {
  cat <<'HELP'
format-exporters-v2/install-functions.sh — установить Actions экспорта версии V2.

Параметры:
  --all              установить images, documents, code и data (по умолчанию все группы)
  --img              добавить группу images
  --doc              добавить группу documents
  --code             добавить группу code
  --data             добавить группу data
  --url URL          базовый URL Open WebUI (по умолчанию OWUI_URL или http://127.0.0.1:8080)
  --user URL          устаревший псевдоним --url
  --email EMAIL      e-mail администратора (по умолчанию OWUI_ADMIN_EMAIL; иначе запрос)
  --container NAME   контейнер Open WebUI (по умолчанию open-webui)
  --version, -V      вывести версию установщика
  -h, --help         показать эту справку

Пароль администратора запрашивается скрыто. Нужны Docker и запущенный Open WebUI.

Примеры:
  ./install-functions.sh
  ./install-functions.sh --doc --data
  ./install-functions.sh --img --code --email admin@example.org --url http://127.0.0.1:8080
HELP
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all) PLUGIN_GROUPS=(images documents code data); shift ;;
    --img) PLUGIN_GROUPS+=(images); shift ;;
    --doc) PLUGIN_GROUPS+=(documents); shift ;;
    --code) PLUGIN_GROUPS+=(code); shift ;;
    --data) PLUGIN_GROUPS+=(data); shift ;;
    --email) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; EMAIL="$2"; shift 2 ;;
    --container) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; CONT="$2"; shift 2 ;;
    --url|--user) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; URL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ ${#PLUGIN_GROUPS[@]} -gt 0 ]] || PLUGIN_GROUPS=(images documents code data)
mapfile -t PLUGIN_GROUPS < <(printf '%s\n' "${PLUGIN_GROUPS[@]}" | awk '!seen[$0]++')
docker inspect -f '{{.State.Running}}' "$CONT" | grep -q true || { echo "ERROR: container $CONT is not running" >&2; exit 1; }
if [[ -z "$EMAIL" ]]; then
  [[ -r /dev/tty ]] || { echo "ERROR: pass --email ADMIN_EMAIL" >&2; exit 1; }
  read -r -p 'Open WebUI admin e-mail: ' EMAIL </dev/tty
fi
[[ -n "$EMAIL" ]] || { echo "ERROR: admin e-mail is empty" >&2; exit 1; }
[[ -r /dev/tty ]] || { echo "ERROR: no terminal to read password" >&2; exit 1; }
read -r -s -p "Password for $EMAIL: " PASS </dev/tty
echo >/dev/tty
[[ -n "$PASS" ]] || { echo "ERROR: admin password is empty" >&2; exit 1; }
case "${URL%/}" in
  http://127.0.0.1:8080|http://localhost:3000) API_URL="http://127.0.0.1:8080" ;;
esac
echo "Installing ${PLUGIN_GROUPS[*]} through container $CONT (API $API_URL)..."
TMPD="/tmp/owui-export-manager-$$"
trap 'docker exec "$CONT" rm -rf "$TMPD" >/dev/null 2>&1 || true' EXIT
docker exec "$CONT" mkdir -p "$TMPD"
docker cp "$HERE/manage-functions.py" "$CONT:$TMPD/"
for group in "${PLUGIN_GROUPS[@]}"; do
  docker exec "$CONT" mkdir -p "$TMPD/$group"
  docker cp "$HERE/$group/functions/export_action.py" "$CONT:$TMPD/$group/"
done
printf '%s\n' "$PASS" | docker exec -i "$CONT" python3 "$TMPD/manage-functions.py" \
  --url "$API_URL" --email "$EMAIL" --operation install --groups "${PLUGIN_GROUPS[@]}" --dir "$TMPD"
