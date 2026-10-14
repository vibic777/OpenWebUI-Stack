#!/usr/bin/env bash
SCRIPT_VERSION="2026.09.25.1"
for arg in "$@"; do case "$arg" in -h|--help) echo "Устанавливает экспортёр временных меток сообщений как Open WebUI Function. Дополнительные параметры передаются установщику Python."; exit 0;; esac; done
for version_arg in "$@"; do
  case "$version_arg" in --version|-V) printf '%s %s\n' "$(basename "$0")" "$SCRIPT_VERSION"; exit 0;; esac
done
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/functions/install_functions.py" "$@"
