#!/usr/bin/env bash
# Read-only Valkey protocol probe.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
check-valkey.sh — проверить сетевое соединение с Valkey и выполнить PING.
Проверка не меняет и не очищает данные кэша.

Аргументы: не принимает параметры, кроме -h/--help.
Требования: запущенный контейнер Valkey и доступный контейнер Open WebUI.

Примеры:
  ./check-valkey.sh
  cd /path/to/openwebui-stack && ./check-valkey.sh
HELP
  exit 0
fi
(( $# == 0 )) || ops_die "аргументы не поддерживаются; используйте --help"
docker inspect -f '{{.State.Running}}' openwebui-valkey 2>/dev/null | grep -q true \
  || ops_die "openwebui-valkey is not running; inspect container status/logs"
reply="$(docker exec openwebui-valkey sh -c 'valkey-cli ping 2>/dev/null || redis-cli ping 2>/dev/null' 2>/dev/null | tail -1 | tr -d '\r')"
[[ "${reply,,}" == pong ]] || ops_die "Valkey did not return PONG; inspect docker logs openwebui-valkey and port 6379"
echo "PASS  Valkey PING"
