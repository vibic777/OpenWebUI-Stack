#!/usr/bin/env bash
# Refresh the image currently configured in the primary Compose .env.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
YES=0; DRY=0; PULL=0; ACTION=update
STATE_DIR="$HERE/.openwebui-current-update-state"
KEY_FILE="$HERE/.webui_secret_key"

usage() {
  cat <<'HELP'
Использование:
  ./update-openwebui-current.sh [--pull] [--yes] [--dry-run]
  ./update-openwebui-current.sh rollback [--yes] [--dry-run]

Обновляет образ, указанный в OPENWEBUI_IMAGE, сохраняя registry и tag. Ключ
--pull явно скачивает образ; по умолчанию скрипт работает офлайн и требует,
чтобы образ уже был загружен локально. Пересоздаётся только open-webui.
Перед обновлением создаётся резервная копия БД и сохраняется точный образ
для отката. docker-compose.yml не редактируется.
HELP
}
while (( $# > 0 )); do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --pull) PULL=1; shift ;;
    -y|--yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    rollback) ACTION=rollback; shift ;;
    *) ops_die "unknown argument: $1" ;;
  esac
done
cd "$HERE"
[[ -f .env && ! -L .env ]] || ops_die ".env must be a regular file"
DC="$(ops_compose "$HERE")"
FILES="$(ops_files "$HERE")"
confirm() { (( YES == 1 || DRY == 1 )) && return 0; read -r -p "$1 [y/N] " a; [[ "$a" == y || "$a" == Y || "$a" == yes ]]; }

set_compose_image() {
  local image="$1" key_path="${2:-}"
  OPENWEBUI_TARGET_IMAGE="$image" WEBUI_SIGNING_KEY_FILE="$key_path" python3 - .env <<'PY'
from pathlib import Path
import os, re, sys, tempfile
p = Path(sys.argv[1]); vals = {"OPENWEBUI_IMAGE": os.environ["OPENWEBUI_TARGET_IMAGE"]}
kf = os.environ.get("WEBUI_SIGNING_KEY_FILE", "")
if kf:
    key = Path(kf).read_text().strip()
    if not key: raise SystemExit("signing key file is empty")
    vals["WEBUI_SECRET_KEY"] = key
seen = set(); out = []
for line in p.read_text().splitlines():
    m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line); name = m.group(1) if m else None
    if name in vals:
        if name not in seen: out.append(f"{name}={vals[name]}"); seen.add(name)
    else: out.append(line)
for n, v in vals.items():
    if n not in seen: out.append(f"{n}={v}")
fd, tmp = tempfile.mkstemp(prefix=".env.update.", dir=p.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f: f.write("\n".join(out) + "\n")
    os.chmod(tmp, 0o600); os.replace(tmp, p)
except BaseException:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
    raise
PY
}

if [[ "$ACTION" == rollback ]]; then
  shopt -s nullglob; states=("$STATE_DIR"/*.state); shopt -u nullglob
  (( ${#states[@]} > 0 )) || ops_die "no saved update state"
  STATE="${states[-1]}"
  # State files are created here with mode 600.
  # shellcheck disable=SC1090
  source "$STATE"
  [[ -n "${OLD_LOCAL_IMAGE:-}" && -n "${OLD_IMAGE:-}" ]] || ops_die "invalid state file"
  docker image inspect "$OLD_LOCAL_IMAGE" >/dev/null 2>&1 || ops_die "saved old image is missing"
  if (( DRY == 1 )); then echo "DRY-RUN: restore $OLD_LOCAL_IMAGE"; exit 0; fi
  confirm "Restore previous Open WebUI image $OLD_IMAGE?" || ops_die "cancelled"
  set_compose_image "$OLD_LOCAL_IMAGE"
  $DC $FILES --env-file .env up -d --no-deps --pull never open-webui
  ops_info "restored $OLD_IMAGE; rollback state retained"
  exit 0
fi

CURRENT_REF="$(ops_env_get .env OPENWEBUI_IMAGE)"
CURRENT_REF="${CURRENT_REF:-openwebui/open-webui:latest}"
docker inspect -f '{{.State.Running}}' open-webui 2>/dev/null | grep -q true || ops_die "open-webui is not running"
docker inspect -f '{{.State.Running}}' openwebui-postgres 2>/dev/null | grep -q true || ops_die "openwebui-postgres is not running"
CURRENT_IMAGE="$(docker inspect --format '{{.Config.Image}}' open-webui)"
CURRENT_ID="$(docker inspect --format '{{.Image}}' open-webui)"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOCAL_IMAGE="openwebui-current:rollback-$STAMP"
STATE="$STATE_DIR/$STAMP.state"
if (( DRY == 1 )); then
  (( PULL == 1 )) && echo "DRY-RUN: pull latest $CURRENT_REF" || echo "DRY-RUN: require refreshed local $CURRENT_REF"
  echo "DRY-RUN: save key, DB backup, image snapshot $LOCAL_IMAGE; refresh only open-webui"
  exit 0
fi
confirm "Backup DB and refresh current image $CURRENT_REF?" || ops_die "cancelled"
if (( PULL == 1 )); then
  OPENWEBUI_IMAGE="$CURRENT_REF" $DC $FILES --env-file .env pull open-webui
else
  docker image inspect "$CURRENT_REF" >/dev/null 2>&1 || ops_die "load refreshed $CURRENT_REF locally first or pass --pull"
fi
KEY_TMP="$HERE/.webui_secret_key.check.$$"
trap 'rm -f -- "${KEY_TMP:-}"' EXIT
docker cp open-webui:/app/backend/.webui_secret_key "$KEY_TMP" >/dev/null || ops_die "could not read current signing key"
[[ -s "$KEY_TMP" ]] || ops_die "current signing key is empty"
if [[ -s "$KEY_FILE" ]]; then
  cmp -s "$KEY_FILE" "$KEY_TMP" || ops_die "saved signing key differs from running container"
  rm -f -- "$KEY_TMP"
else
  chmod 600 "$KEY_TMP"; mv -- "$KEY_TMP" "$KEY_FILE"
fi
trap - EXIT
"$HERE/backup-stack.sh" --db-only --no-config
docker tag "$CURRENT_ID" "$LOCAL_IMAGE"
umask 077; mkdir -p "$STATE_DIR"
{
  printf 'OLD_IMAGE=%q\n' "$CURRENT_IMAGE"
  printf 'OLD_LOCAL_IMAGE=%q\n' "$LOCAL_IMAGE"
  printf 'OLD_IMAGE_ID=%q\n' "$CURRENT_ID"
} > "$STATE"
chmod 600 "$STATE"
set_compose_image "$CURRENT_REF" "$KEY_FILE"
$DC $FILES --env-file .env up -d --no-deps --pull never open-webui
ops_info "refreshed $CURRENT_REF; DB backup completed"
ops_info "rollback command: ./update-openwebui-current.sh rollback"
