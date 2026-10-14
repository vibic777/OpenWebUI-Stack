#!/usr/bin/env bash
# Update only the Open WebUI service through the primary Compose configuration.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

PREFIX="ghcr.io/open-webui/open-webui:"
TAG=main; PULL=0; YES=0; DRY=0
STATE_DIR="$HERE/.openwebui-update-state"
KEY_FILE="$HERE/.webui_secret_key"

usage() {
  cat <<'HELP'
Использование:
  ./update-openwebui-ghcr.sh [TAG] [--pull] [--yes] [--dry-run]
  ./update-openwebui-ghcr.sh rollback [--yes] [--dry-run]

По умолчанию цель — ghcr.io/open-webui/open-webui:main (изменяемый тег).
Передайте фиксированный тег выпуска, например v0.11.4, для конкретной версии.
Офлайн по умолчанию: целевой образ должен быть заранее загружен локально.
--pull явно скачивает его из GHCR.

Перед обновлением создаётся резервная копия PostgreSQL, сохраняется текущий
WEBUI_SECRET_KEY и локальная копия точного старого образа. Обновляется только
open-webui. rollback возвращает последний сохранённый образ и записывает его
ссылку в .env. Основной docker-compose.yml не меняется.
HELP
}

while (( $# > 0 )); do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --pull) PULL=1; shift ;;
    -y|--yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    rollback) TAG=rollback; shift ;;
    --*) ops_die "unknown argument: $1" ;;
    *) [[ "$TAG" == main ]] || ops_die "only one image tag may be specified"; TAG="$1"; shift ;;
  esac
done

cd "$HERE"
[[ -f .env && ! -L .env ]] || ops_die ".env must be a regular file"
DC="$(ops_compose "$HERE")"
FILES="$(ops_files "$HERE")"

confirm() {
  (( YES == 1 || DRY == 1 )) && return 0
  read -r -p "$1 [y/N] " answer
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes ]]
}

# Atomically edit only the named settings, without printing their values.
set_compose_image() {
  local image="$1" key_path="${2:-}"
  OPENWEBUI_TARGET_IMAGE="$image" WEBUI_SIGNING_KEY_FILE="$key_path" python3 - .env <<'PY'
from pathlib import Path
import os
import re
import sys
import tempfile

path = Path(sys.argv[1])
image = os.environ["OPENWEBUI_TARGET_IMAGE"]
key_file = os.environ.get("WEBUI_SIGNING_KEY_FILE", "")
key = Path(key_file).read_text().strip() if key_file else None
if key_file and not key:
    raise SystemExit("signing key file is empty")

text = path.read_text()
lines = text.splitlines()
values = {"OPENWEBUI_IMAGE": image}
if key is not None:
    values["WEBUI_SECRET_KEY"] = key
seen = set()
out = []
for line in lines:
    match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
    name = match.group(1) if match else None
    if name in values:
        if name not in seen:
            out.append(f"{name}={values[name]}")
            seen.add(name)
        continue
    out.append(line)
for name, value in values.items():
    if name not in seen:
        out.append(f"{name}={value}")

fd, temp_name = tempfile.mkstemp(prefix=".env.update.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(out) + "\n")
    os.chmod(temp_name, 0o600)
    os.replace(temp_name, path)
except BaseException:
    try:
        os.unlink(temp_name)
    except FileNotFoundError:
        pass
    raise
PY
}

if [[ "$TAG" == rollback ]]; then
  shopt -s nullglob
  states=("$STATE_DIR"/*.state)
  shopt -u nullglob
  (( ${#states[@]} > 0 )) || ops_die "no saved update state; nothing to roll back"
  STATE="${states[-1]}"
  # State files are created by this script with mode 600.
  # shellcheck disable=SC1090
  source "$STATE"
  [[ -n "${OLD_LOCAL_IMAGE:-}" && -n "${OLD_IMAGE:-}" ]] || ops_die "invalid state file: $STATE"
  docker image inspect "$OLD_LOCAL_IMAGE" >/dev/null 2>&1 || ops_die "saved old image is missing: $OLD_LOCAL_IMAGE"
  ROLLBACK_REF="$OLD_LOCAL_IMAGE"
  if [[ -n "${OLD_IMAGE_ID:-}" ]] \
    && docker image inspect "$OLD_IMAGE" >/dev/null 2>&1 \
    && [[ "$(docker image inspect "$OLD_IMAGE" --format '{{.Id}}')" == "$OLD_IMAGE_ID" ]]; then
    ROLLBACK_REF="$OLD_IMAGE"
  fi
  [[ -n "$(ops_env_get .env WEBUI_SECRET_KEY)" ]] || ops_die "WEBUI_SECRET_KEY is not persisted in .env"
  if (( DRY == 1 )); then
    echo "DRY-RUN: set OPENWEBUI_IMAGE=$ROLLBACK_REF and recreate only open-webui"
    exit 0
  fi
  confirm "Restore Open WebUI to previous image $OLD_IMAGE?" || ops_die "cancelled"
  set_compose_image "$ROLLBACK_REF"
  $DC $FILES --env-file .env up -d --no-deps --pull never open-webui
  ops_info "rolled back to $OLD_IMAGE; .env now points to $ROLLBACK_REF"
  ops_info "state retained at $STATE"
  exit 0
fi

[[ "$TAG" =~ ^[A-Za-z0-9_.-]+$ ]] || ops_die "invalid GHCR tag: $TAG"
TARGET="${PREFIX}${TAG}"
docker inspect -f '{{.State.Running}}' open-webui 2>/dev/null | grep -q true || ops_die "open-webui is not running"
docker inspect -f '{{.State.Running}}' openwebui-postgres 2>/dev/null | grep -q true || ops_die "openwebui-postgres is not running"
CURRENT_IMAGE="$(docker inspect --format '{{.Config.Image}}' open-webui)"
CURRENT_ID="$(docker inspect --format '{{.Image}}' open-webui)"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOCAL_IMAGE="openwebui-update:rollback-$STAMP"
STATE="$STATE_DIR/$STAMP.state"

if (( DRY == 1 )); then
  (( PULL == 1 )) && echo "DRY-RUN: pull $TARGET" || echo "DRY-RUN: require local image $TARGET"
  echo "DRY-RUN: preserve signing key in .env; create DB backup; tag old image $LOCAL_IMAGE"
  echo "DRY-RUN: set OPENWEBUI_IMAGE=$TARGET and recreate only open-webui"
  exit 0
fi
confirm "Backup DB and update only Open WebUI: $CURRENT_IMAGE -> $TARGET?" || ops_die "cancelled"

# Resolve target before persistent configuration or data changes.
if (( PULL == 1 )); then
  OPENWEBUI_IMAGE="$TARGET" $DC $FILES --env-file .env pull open-webui
else
  docker image inspect "$TARGET" >/dev/null 2>&1 \
    || ops_die "image $TARGET is not loaded locally; transfer/load it first, or use --pull on a networked host"
fi

KEY_TMP="$HERE/.webui_secret_key.check.$$"
trap 'rm -f -- "${KEY_TMP:-}"' EXIT
docker cp open-webui:/app/backend/.webui_secret_key "$KEY_TMP" >/dev/null \
  || ops_die "could not read current signing key from the running container"
[[ -s "$KEY_TMP" ]] || ops_die "current signing key is empty"
if [[ -s "$KEY_FILE" ]]; then
  cmp -s "$KEY_FILE" "$KEY_TMP" || ops_die "saved signing key differs from running container; refusing update"
  rm -f -- "$KEY_TMP"
else
  chmod 600 "$KEY_TMP"
  mv -- "$KEY_TMP" "$KEY_FILE"
fi
trap - EXIT

"$HERE/backup-stack.sh" --db-only --no-config
docker tag "$CURRENT_ID" "$LOCAL_IMAGE"
umask 077
mkdir -p "$STATE_DIR"
{
  printf 'OLD_IMAGE=%q\n' "$CURRENT_IMAGE"
  printf 'OLD_LOCAL_IMAGE=%q\n' "$LOCAL_IMAGE"
  printf 'OLD_IMAGE_ID=%q\n' "$CURRENT_ID"
  printf 'NEW_IMAGE=%q\n' "$TARGET"
} > "$STATE"
chmod 600 "$STATE"
set_compose_image "$TARGET" "$KEY_FILE"
$DC $FILES --env-file .env up -d --no-deps --pull never open-webui
ops_info "updated Open WebUI to $TARGET; DB backup completed"
ops_info "rollback command: ./update-openwebui-ghcr.sh rollback"
