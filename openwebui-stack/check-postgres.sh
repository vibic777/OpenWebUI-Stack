#!/usr/bin/env bash
# Read-only PostgreSQL connectivity and schema probe.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
check-postgres.sh — read-only проверка подключения PostgreSQL и схемы Open WebUI.
Не меняет записи и не создаёт тестовые данные.

Аргументы: не принимает параметры, кроме -h/--help.
Требования: запущенный контейнер openwebui-postgres и доступный файл .env.

Примеры:
  ./check-postgres.sh
  cd /path/to/openwebui-stack && ./check-postgres.sh
HELP
  exit 0
fi
(( $# == 0 )) || ops_die "аргументы не поддерживаются; используйте --help"
ENVF="$HERE/.env"
DBN="$(ops_env_get "$ENVF" POSTGRES_DB)"
DBU="$(ops_env_get "$ENVF" POSTGRES_USER)"
PGPASSWORD="${PGPASSWORD:-$(ops_env_get "$ENVF" POSTGRES_PASSWORD)}"
export PGPASSWORD
[[ -n "$DBN" && -n "$DBU" && -n "$PGPASSWORD" ]] || ops_die "POSTGRES_DB/USER/PASSWORD missing in $ENVF (or set PGPASSWORD)"
docker inspect -f '{{.State.Running}}' openwebui-postgres 2>/dev/null | grep -q true \
  || ops_die "openwebui-postgres is not running; inspect ./verify-stack.sh and container logs"
if counts="$(docker exec -e PGPASSWORD openwebui-postgres psql -U "$DBU" -d "$DBN" -v ON_ERROR_STOP=1 -Atc \
  "select 'users='||(select count(*) from \"user\")||' chats='||(select count(*) from chat)||' groups='||(select count(*) from \"group\")" 2>&1)"; then
  echo "PASS  PostgreSQL connection and Open WebUI schema: $counts"
else
  ops_die "PostgreSQL query failed; check POSTGRES_DB/USER/PASSWORD, schema migrations, and docker logs openwebui-postgres: $counts"
fi
