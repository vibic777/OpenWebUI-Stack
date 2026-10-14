#!/usr/bin/env bash
# backup-stack.sh — backup Postgres (users, roles, groups, permissions, chats, settings)
# + secret key volume + optional Qdrant/SeaweedFS volumes + configs.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "backup-stack.sh — backup Open WebUI database and data (works offline)." \
    "backup-stack.sh — бэкап базы Open WebUI и данных (работает без интернета)."
  cat <<'HELP'
Использование:
  ./backup-stack.sh [--out DIR] [MODE] [options]

MODE (one of / одно из):
  (default)      DB + globals + openwebui_data volume (JWT secret key, uploads cache) + configs.
                 Hot: the stack keeps running. / Стек не останавливается.
  --db-only      only PostgreSQL dump (users, roles, groups, permissions, chats, settings)
  --full         default + Qdrant vectors + SeaweedFS files. Stops open-webui/qdrant/seaweedfs
                 for the copy, then starts them again. / Кратко останавливает сервисы.

Options / Параметры:
  --out DIR          backup root (default: ~/backups)
  --no-config        do not copy .env / nginx / s3.json (they contain secrets)
  --keep N           keep only the newest N backups of this target in --out
  --container NAME   postgres container (default: openwebui-postgres)
  --db-name NAME     database (default: POSTGRES_DB from .env)
  --db-user USER     role (default: POSTGRES_USER from .env)
  --ask-password     ask DB password interactively (otherwise: $PGPASSWORD, else POSTGRES_PASSWORD from .env)
  --dry-run          print plan only
  -h, --help         эта справка

Password: never put it on the command line (visible in `ps`). Use $PGPASSWORD or --ask-password.
Result: DIR/owui-<target>-<timestamp>/ (db.dump, globals.sql, *.tgz, MANIFEST.txt, SHA256SUMS), mode 700.
Restore: ./restore-stack.sh --from <that dir>

Examples / Примеры:
  ./backup-stack.sh
  ./backup-stack.sh --db-only --keep 14
HELP
}

TARGET="$(basename "$HERE")"; OUT="$HOME/backups"; MODE=std; CONFIG=1; KEEP=0; DRY=0; ASK=0
CONT=openwebui-postgres; DBN=""; DBU=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --out) OUT="$2"; shift 2 ;;
    --db-only) MODE=db; shift ;;
    --full) MODE=full; shift ;;
    --no-config) CONFIG=0; shift ;;
    --keep) KEEP="$2"; shift 2 ;;
    --container) CONT="$2"; shift 2 ;;
    --db-name) DBN="$2"; shift 2 ;;
    --db-user) DBU="$2"; shift 2 ;;
    --ask-password) ASK=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
DIR="$HERE"; DC="$(ops_compose "$DIR")"; ENVF="$DIR/.env"
DBN="${DBN:-$(ops_env_get "$ENVF" POSTGRES_DB)}"; DBU="${DBU:-$(ops_env_get "$ENVF" POSTGRES_USER)}"
[[ -n "$DBN" && -n "$DBU" ]] || ops_die "DB name/user unknown: set POSTGRES_DB/POSTGRES_USER in $ENVF or use --db-name/--db-user"
if [[ $ASK -eq 1 ]]; then read -r -s -p "PostgreSQL password for $DBU: " PGPASSWORD; echo; fi
PGPASSWORD="${PGPASSWORD:-$(ops_env_get "$ENVF" POSTGRES_PASSWORD)}"; export PGPASSWORD

TS="$(date +%Y%m%d-%H%M%S)"; DEST="$OUT/owui-$TARGET-$TS"
ops_info "backup target=$TARGET mode=$MODE db=$DBN user=$DBU -> $DEST"
if [[ $DRY -eq 1 ]]; then
  echo "DRY-RUN: pg_dump -Fc + pg_dumpall --globals-only in $CONT; mode=$MODE"
  exit 0
fi
docker inspect -f '{{.State.Running}}' "$CONT" 2>/dev/null | grep -q true || ops_die "container $CONT is not running (start the stack first)"
umask 077; mkdir -p "$DEST"
PGIMG="$(docker inspect -f '{{.Config.Image}}' "$CONT")"   # already present locally: reused for tar (no extra image needed)

# 1) PostgreSQL: consistent online dump
docker exec -e PGPASSWORD "$CONT" pg_dump -U "$DBU" -d "$DBN" -Fc --no-owner > "$DEST/db.dump"
docker exec -e PGPASSWORD "$CONT" pg_dumpall -U "$DBU" --globals-only > "$DEST/globals.sql"
[[ -s "$DEST/db.dump" ]] || ops_die "empty dump"
docker exec -e PGPASSWORD "$CONT" psql -U "$DBU" -d "$DBN" -Atc \
  "select 'users='||(select count(*) from \"user\")||' chats='||(select count(*) from chat)||' groups='||(select count(*) from \"group\")" \
  > "$DEST/db-counts.txt" 2>/dev/null || echo "counts: n/a" > "$DEST/db-counts.txt"

vol_tar() { # container dest name
  local c="$1" d="$2" n="$3" v
  v="$(ops_container_volume "$c" "$d")"; [[ -n "$v" ]] || { ops_info "skip $n: no named volume on $c:$d"; return 0; }
  ops_info "volume $v -> $n.tgz"
  docker run --rm --entrypoint sh -v "$v:/from:ro" -v "$DEST:/to" "$PGIMG" -c     "tar czf /to/$n.tgz -C /from . && chown $(id -u):$(id -g) /to/$n.tgz && chmod 600 /to/$n.tgz"
}
# 2) volumes
if [[ $MODE != db ]]; then
  vol_tar open-webui /app/backend/data openwebui_data
fi
if [[ $MODE == full ]]; then
  cd "$DIR"; FILES="$(ops_files "$DIR")"
  ops_info "stopping open-webui qdrant seaweedfs for a consistent copy"
  trap 'cd "$DIR"; $DC $FILES --env-file .env start open-webui qdrant seaweedfs >/dev/null 2>&1 || true' EXIT
  $DC $FILES --env-file .env stop open-webui qdrant seaweedfs
  vol_tar openwebui-qdrant /qdrant/storage qdrant_storage
  vol_tar openwebui-seaweedfs /data seaweedfs_data
fi
# 3) configs (secrets!)
if [[ $CONFIG -eq 1 && $MODE != db ]]; then
  ( cd "$DIR" && tar czf "$DEST/config.tgz" .env docker-compose*.yml seaweedfs/s3.json nginx 2>/dev/null ) || true
fi
{
  echo "target=$TARGET mode=$MODE ts=$TS host=$(hostname)"
  echo "db=$DBN user=$DBU"
  echo "openwebui_image=$(docker inspect -f '{{.Config.Image}}' open-webui 2>/dev/null || true)"
  cat "$DEST/db-counts.txt"
} > "$DEST/MANIFEST.txt"
( cd "$DEST" && sha256sum ./* > SHA256SUMS )
ops_info "OK: $DEST ($(du -sh "$DEST" | cut -f1)); $(cat "$DEST/db-counts.txt")"
if [[ $CONFIG -eq 1 && $MODE != db ]]; then ops_info "NOTE: config.tgz contains secrets — store it safely"; fi
if [[ "$KEEP" -gt 0 ]]; then
  ls -1d "$OUT"/owui-"$TARGET"-* 2>/dev/null | sort | head -n -"$KEEP" | while read -r old; do ops_info "rotate: remove $old"; rm -rf -- "$old"; done
fi
