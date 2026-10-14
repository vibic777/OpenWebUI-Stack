#!/usr/bin/env bash
SCRIPT_VERSION="2026.09.25.1"
for version_arg in "$@"; do
  case "$version_arg" in --version|-V) printf '%s %s\n' "$(basename "$0")" "$SCRIPT_VERSION"; exit 0;; esac
done
# remove-functions.sh — remove Open WebUI Functions (plugins) on THIS server (the reverse of install-functions.sh).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() {
  cat <<'HELP'
remove-functions.sh — remove Open WebUI plugins / удалить плагины Open WebUI

Использование:
  ./remove-functions.sh --all   [--email E] [--ask-password] [--dry-run]     remove every plugin of this bundle
  ./remove-functions.sh --id ID [--id ID2] [--email E] [--ask-password]      remove selected (export_office, token_and_time, message_timestamps)
  ./remove-functions.sh --list                                               show what is installed

Removes only the Function records in Open WebUI (the .py files here stay). Chats, users and messages are untouched.
NOTE: timestamps already appended to old messages by message_timestamps stay as plain text in those messages.
Manual alternative: Admin -> Functions -> the function -> ... -> Delete.  Other machine: python functions/install_functions.py --url ... --remove ID
HELP
}
ARGS=(); PASSTHRU=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --all) ARGS+=(--remove-bundled); shift ;;
    --id) ARGS+=(--remove "$2"); shift 2 ;;
    --list) ARGS+=(--list); shift ;;
    --email|--container|--url) PASSTHRU+=("$1" "$2"); shift 2 ;;
    --ask-password) PASSTHRU+=("$1"); shift ;;
    --dry-run) echo "dry-run is not supported by the wrapper; use: python functions/install_functions.py ... --remove-bundled --dry-run"; exit 2 ;;
    *) echo "unknown arg: $1 (try --help)" >&2; exit 1 ;;
  esac
done
[[ ${#ARGS[@]} -gt 0 ]] || { usage; exit 1; }
exec "$HERE/install-functions.sh" "${PASSTHRU[@]}" "${ARGS[@]}"
