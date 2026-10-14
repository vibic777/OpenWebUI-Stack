#!/usr/bin/env bash
# restore-stack.sh — restore a backup made by backup-stack.sh.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "restore-stack.sh — restore Open WebUI DB (users, roles, chats, permissions) and data from backup." \
    "restore-stack.sh — восстановить базу (пользователи, роли, чаты, права) и данные из бэкапа."
  cat <<'HELP'
Использование:
  ./restore-stack.sh --from BACKUP_DIR [options]

Options / Параметры:
  --from DIR         backup dir made by backup-stack.sh (required)
  --db-only          restore only PostgreSQL (default: DB + openwebui_data if present in backup)
  --with-vectors     also restore Qdrant + SeaweedFS volumes (only if backup was --full)
  --container NAME   postgres container (default: openwebui-postgres)
  --db-name / --db-user   override .env values
  --ask-password     ask DB password (else $PGPASSWORD, else POSTGRES_PASSWORD from .env)
  -y, --yes          no confirmation (or CONFIRM=yes)
  --dry-run          print plan only
  -h, --help         эта справка

What happens: open-webui is stopped, the database is DROPPED and re-created from db.dump,
volumes are replaced from *.tgz, open-webui is started. The current state is LOST
=> make a fresh ./backup-stack.sh first.  Never uses `down -v`.
HELP
}
FROM=""; TARGET="$(basename "$HERE")"; DBONLY=0; VEC=0; YES=0; DRY=0; ASK=0; CONT=openwebui-postgres; DBN=""; DBU=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --from) FROM="$2"; shift 2 ;;
    --db-only) DBONLY=1; shift ;;
    --with-vectors) VEC=1; shift ;;
    --container) CONT="$2"; shift 2 ;;
    --db-name) DBN="$2"; shift 2 ;;
    --db-user) DBU="$2"; shift 2 ;;
    --ask-password) ASK=1; shift ;;
    -y|--yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
[[ -f "$FROM/db.dump" ]] || ops_die "--from DIR with db.dump required"
if [[ -f "$FROM/SHA256SUMS" ]]; then ( cd "$FROM" && sha256sum -c SHA256SUMS >/dev/null ) || ops_die "backup checksum mismatch"; fi
DIR="$HERE"; DC="$(ops_compose "$DIR")"; ENVF="$DIR/.env"; FILES="$(ops_files "$DIR")"
DBN="${DBN:-$(ops_env_get "$ENVF" POSTGRES_DB)}"; DBU="${DBU:-$(ops_env_get "$ENVF" POSTGRES_USER)}"
[[ -n "$DBN" && -n "$DBU" ]] || ops_die "DB name/user unknown (use --db-name/--db-user)"
if [[ $ASK -eq 1 ]]; then read -r -s -p "PostgreSQL password for $DBU: " PGPASSWORD; echo; fi
PGPASSWORD="${PGPASSWORD:-$(ops_env_get "$ENVF" POSTGRES_PASSWORD)}"; export PGPASSWORD
cat "$FROM/MANIFEST.txt" 2>/dev/null || true
PLAN="stop open-webui; DROP+CREATE database $DBN; pg_restore db.dump"
if [[ $DBONLY -eq 0 && -f "$FROM/openwebui_data.tgz" ]]; then PLAN="$PLAN; replace openwebui_data volume"; fi
if [[ $VEC -eq 1 ]]; then PLAN="$PLAN; replace qdrant + seaweedfs volumes"; fi
echo "PLAN: $PLAN; start open-webui"
[[ $DRY -eq 1 ]] && exit 0
if [[ $YES -ne 1 && "${CONFIRM:-}" != "yes" ]]; then
  read -r -p "Type 'restore' to overwrite the CURRENT $TARGET data: " a
  [[ "$a" == "restore" ]] || ops_die "cancelled"
fi
cd "$DIR"
$DC $FILES --env-file .env up -d postgres >/dev/null
for _ in $(seq 1 30); do docker exec "$CONT" pg_isready -U "$DBU" >/dev/null 2>&1 && break; sleep 2; done
docker exec "$CONT" pg_isready -U "$DBU" >/dev/null || ops_die "postgres not ready"
PGIMG="$(docker inspect -f '{{.Config.Image}}' "$CONT")"
$DC $FILES --env-file .env stop open-webui
ops_info "recreate database $DBN"
docker exec -e PGPASSWORD "$CONT" psql -U "$DBU" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$DBN\" WITH (FORCE)" -c "CREATE DATABASE \"$DBN\" OWNER \"$DBU\""
ops_info "pg_restore"
docker exec -i -e PGPASSWORD "$CONT" pg_restore -U "$DBU" -d "$DBN" --no-owner --exit-on-error < "$FROM/db.dump"
vol_untar() { # container dest name  (volume content is replaced)
  local c="$1" d="$2" n="$3" v
  [[ -f "$FROM/$n.tgz" ]] || { ops_info "no $n.tgz in backup, skip"; return 0; }
  v="$(ops_container_volume "$c" "$d")"; [[ -n "$v" ]] || ops_die "no volume for $c:$d"
  ops_info "replace volume $v from $n.tgz"
  docker run --rm --entrypoint sh -v "$v:/to" -v "$FROM:/from:ro" "$PGIMG" -c "find /to -mindepth 1 -delete && tar xzf /from/$n.tgz -C /to"
}
if [[ $DBONLY -eq 0 ]]; then vol_untar open-webui /app/backend/data openwebui_data; fi
if [[ $VEC -eq 1 ]]; then
  $DC $FILES --env-file .env stop qdrant seaweedfs
  vol_untar openwebui-qdrant /qdrant/storage qdrant_storage
  vol_untar openwebui-seaweedfs /data seaweedfs_data
  $DC $FILES --env-file .env start qdrant seaweedfs
fi
$DC $FILES --env-file .env up -d
ops_info "waiting for open-webui to become healthy (up to 3 min)"
for _ in $(seq 1 36); do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' open-webui 2>/dev/null)" == "healthy" ]] && break; sleep 5
done
ops_info "restored. Check: ./verify-stack.sh ; then log in and check users/chats."
