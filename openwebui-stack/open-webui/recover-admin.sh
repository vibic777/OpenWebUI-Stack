#!/usr/bin/env bash
# Сброс пароля / роли админа Open WebUI без Python на хосте.
# SSH на Docker-хост. Не down -v, не DELETE, не volume rm.
# Пароль: docker exec open-webui (bcrypt) + docker exec openwebui-postgres (psql).
#
#   ./recover-admin.sh list
#   ./recover-admin.sh password you@example.com
#   ./recover-admin.sh promote you@example.com
#   ./recover-admin.sh password you@example.com --promote
#
# То же руками: README.md в этой папке.
set -euo pipefail
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
Использование:
  ./recover-admin.sh list
  ./recover-admin.sh password EMAIL [--promote]
  ./recover-admin.sh promote EMAIL

Показывает пользователей, задаёт пароль или повышает пользователя до
администратора через контейнеры Open WebUI/PostgreSQL. Том БД не удаляется.
HELP
  exit 0
fi

PG_CTR=openwebui-postgres
OWUI_CTR=open-webui

die() { echo "$*" >&2; exit 1; }

sql_escape() { printf '%s' "$1" | sed "s/'/''/g"; }

find_compose_dir() {
  if [[ -n "${COMPOSE_DIR:-}" ]]; then
    if [[ -f "$COMPOSE_DIR/.env" ]]; then
      printf '%s' "$COMPOSE_DIR"
      return
    fi
    die "COMPOSE_DIR=$COMPOSE_DIR: нет .env"
  fi
  local d
  for d in "$PWD" "$(cd "$(dirname "$0")" && pwd)" "$(cd "$(dirname "$0")/.." && pwd)"; do
    if [[ -f "$d/.env" && -f "$d/docker-compose.yml" ]]; then
      printf '%s' "$d"
      return
    fi
  done
  die "не найден .env рядом с docker-compose.yml. cd в каталог стека или COMPOSE_DIR=."
}

env_get() {
  local key=$1 file=$2 line val
  line=$(grep -E "^${key}=" "$file" | tail -n1 || true)
  [[ -n "$line" ]] || die "в .env нет $key"
  val=${line#*=}
  val=${val%\"}
  val=${val#\"}
  val=${val%\'}
  val=${val#\'}
  printf '%s' "$val"
}

docker_ok() {
  local name=$1
  if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)" != "true" ]]; then
    die "контейнер $name не запущен. Не down -v — только up -d."
  fi
}

run_psql() {
  local sql=$1
  docker exec \
    -e "PGPASSWORD=$PGPASSWORD" \
    "$PG_CTR" \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -t -A -c "$sql"
}

check_email() {
  local email
  email=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
  [[ "$email" =~ ^[^@]+@[^@]+\.[^@]+$ ]] || die "нужен обычный email, например admin@example.com"
  printf '%s' "$email"
}

cmd_list() {
  echo "email	role	auth_active"
  local out
  out=$(run_psql "
    SELECT u.email || E'\\t' || COALESCE(u.role, '') || E'\\t' || COALESCE(a.active::text, '')
    FROM \"user\" u
    LEFT JOIN auth a ON a.id = u.id
    ORDER BY u.created_at;
  ")
  if [[ -z "${out//[$'\t\n\r ']/}" ]]; then
    echo "(пользователей нет — регистрация первого даст админа; чаты не трогаем)"
    return
  fi
  printf '%s\n' "$out"
}

hash_password() {
  local password=$1 hashed
  if [[ ${#password} -gt 72 ]]; then
    die "пароль длиннее 72 байт — bcrypt Open WebUI такой не примет"
  fi
  hashed=$(printf '%s' "$password" | docker exec -i "$OWUI_CTR" python -c \
    'import sys,bcrypt; p=sys.stdin.buffer.read(); print(bcrypt.hashpw(p, bcrypt.gensalt()).decode())')
  [[ -n "$hashed" ]] || die "не удалось посчитать хеш в контейнере open-webui"
  printf '%s' "$hashed"
}

cmd_password() {
  local email hashed n password again
  email=$(check_email "$1")
  n=$(run_psql "SELECT count(*) FROM auth WHERE lower(email) = lower('$(sql_escape "$email")');")
  n=${n//$'\n'/}
  [[ "$n" == "1" ]] || die "в auth нет учётки $email. Смотрите list. Нового человека так не создаём."
  read -r -s -p "новый пароль (не отображается): " password
  echo
  [[ -n "$password" ]] || die "пустой пароль нельзя"
  read -r -s -p "ещё раз: " again
  echo
  [[ "$password" == "$again" ]] || die "пароли не совпали"
  hashed=$(hash_password "$password")
  n=$(run_psql "UPDATE auth SET password = '$(sql_escape "$hashed")', active = true WHERE lower(email) = lower('$(sql_escape "$email")') RETURNING email;")
  n=${n//$'\n'/}
  [[ -n "$n" ]] || die "UPDATE auth не затронул строк — ничего не удаляли, проверьте email"
  echo "пароль обновлён для $n. чаты и остальные пользователи без изменений."
  if [[ "${2:-}" == "--promote" ]]; then
    cmd_promote "$email"
  fi
}

cmd_promote() {
  local email n
  email=$(check_email "$1")
  n=$(run_psql "UPDATE \"user\" SET role = 'admin' WHERE lower(email) = lower('$(sql_escape "$email")') RETURNING email || E'\\t' || role;")
  n=${n//$'\n'/}
  [[ -n "$n" ]] || die "в \"user\" нет $email. list покажет, кто есть. никого не удаляли."
  echo "роль admin: ${n//	/ / }"
  echo "остальные пользователи и чаты на месте."
}

ACTION=${1:-}
EMAIL=${2:-}
PROMOTE=${3:-}

[[ -n "$ACTION" ]] || die "usage: $0 list | password EMAIL [--promote] | promote EMAIL"

COMPOSE_DIR=$(find_compose_dir)
ENV_FILE="$COMPOSE_DIR/.env"
POSTGRES_USER=$(env_get POSTGRES_USER "$ENV_FILE")
POSTGRES_PASSWORD=$(env_get POSTGRES_PASSWORD "$ENV_FILE")
POSTGRES_DB=$(env_get POSTGRES_DB "$ENV_FILE")
PGPASSWORD=$POSTGRES_PASSWORD

docker_ok "$PG_CTR"
if [[ "$ACTION" == "password" ]]; then
  docker_ok "$OWUI_CTR"
fi

echo "каталог стека: $COMPOSE_DIR"
echo "тома и пользователи не удаляются."
echo

case "$ACTION" in
  list) cmd_list ;;
  password)
    [[ -n "$EMAIL" ]] || die "укажите email, см. сначала: $0 list"
    cmd_password "$EMAIL" "$PROMOTE"
    ;;
  promote)
    [[ -n "$EMAIL" ]] || die "укажите email, см. сначала: $0 list"
    cmd_promote "$EMAIL"
    ;;
  *) die "неизвестная команда: $ACTION" ;;
esac
