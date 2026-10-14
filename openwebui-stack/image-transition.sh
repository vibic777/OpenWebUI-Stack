#!/usr/bin/env bash
# Safely switch only the Open WebUI image to GHCR v0.11.4 and roll back to the
# exact previously running local image. PostgreSQL and all stack volumes remain intact.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

GHCR_PREFIX="ghcr.io/open-webui/open-webui:"
STATE="$HERE/.image-transition.state"
KEY_FILE="$HERE/.webui_secret_key"
OVERLAY="docker-compose.image-transition.yml"

usage() {
  cat <<'HELP'
Использование:
  ./image-transition.sh switch [--yes] [--dry-run]
  ./image-transition.sh switch --pull [--yes]
  ./image-transition.sh rollback [--yes] [--dry-run]

switch   Сохранить резервную копию БД и текущий ключ, затем переключить только
         Open WebUI на GHCR образ с той же OCI-версией и revision, что у текущего.
rollback Вернуть точный образ Open WebUI, который работал до переключения.
--pull    Явно скачать целевой образ из GHCR (по умолчанию только локальный образ).

Существующие контейнеры БД и тома не удаляются. Основной Compose-файл не меняется.
HELP
}

if (( $# == 0 )); then usage; exit 2; fi
case "$1" in -h|--help) usage; exit 0 ;; esac
ACTION="$1"; shift
YES=0; DRY=0; PULL=0
while (( $# > 0 )); do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -y|--yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --pull) PULL=1; shift ;;
    *) ops_die "unknown argument: $1" ;;
  esac
done
[[ "$ACTION" == switch || "$ACTION" == rollback ]] || ops_die "action must be switch or rollback"

cd "$HERE"
DC="$(ops_compose "$HERE")"
BASE_FILES="$(ops_files "$HERE")"
[[ -f "$HERE/$OVERLAY" ]] || ops_die "missing $OVERLAY"

confirm() {
  (( YES == 1 || DRY == 1 )) && return 0
  read -r -p "$1 [y/N] " answer
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes ]]
}

running_image() {
  docker inspect --format '{{.Config.Image}}' open-webui 2>/dev/null
}

set_compose_image() {
  local image="$1" key_path="${2:-}"
  OPENWEBUI_TARGET_IMAGE="$image" WEBUI_SIGNING_KEY_FILE="$key_path" python3 - .env <<'PY'
from pathlib import Path
import os, re, sys, tempfile
path = Path(sys.argv[1])
values = {"OPENWEBUI_IMAGE": os.environ["OPENWEBUI_TARGET_IMAGE"]}
key_file = os.environ.get("WEBUI_SIGNING_KEY_FILE", "")
if key_file:
    key = Path(key_file).read_text().strip()
    if not key:
        raise SystemExit("signing key file is empty")
    values["WEBUI_SECRET_KEY"] = key
lines = path.read_text().splitlines()
seen, out = set(), []
for line in lines:
    match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
    name = match.group(1) if match else None
    if name in values:
        if name not in seen:
            out.append(f"{name}={values[name]}")
            seen.add(name)
    else:
        out.append(line)
for name, value in values.items():
    if name not in seen:
        out.append(f"{name}={value}")
fd, tmp = tempfile.mkstemp(prefix=".env.transition.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(out) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
except BaseException:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
    raise
PY
}

if [[ "$ACTION" == switch ]]; then
  [[ ! -f "$STATE" ]] || ops_die "transition state already exists; rollback first or inspect $STATE"
  docker inspect -f '{{.State.Running}}' open-webui 2>/dev/null | grep -q true || ops_die "open-webui is not running"
  docker inspect -f '{{.State.Running}}' openwebui-postgres 2>/dev/null | grep -q true || ops_die "openwebui-postgres is not running"

  CURRENT_IMAGE="$(running_image)"
  CURRENT_ID="$(docker inspect --format '{{.Image}}' open-webui)"
  CURRENT_VERSION="$(docker image inspect "$CURRENT_ID" --format '{{ index .Config.Labels "org.opencontainers.image.version" }}')"
  CURRENT_REVISION="$(docker image inspect "$CURRENT_ID" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
  case "$CURRENT_VERSION" in
    main) GHCR_IMAGE="${GHCR_PREFIX}main" ;;
    v[0-9]*.[0-9]*.[0-9]*) GHCR_IMAGE="${GHCR_PREFIX}${CURRENT_VERSION}" ;;
    [0-9]*.[0-9]*.[0-9]*) GHCR_IMAGE="${GHCR_PREFIX}v${CURRENT_VERSION}" ;;
    *) ops_die "unsupported/missing OCI image version '$CURRENT_VERSION'; refusing to guess a same-version GHCR tag" ;;
  esac
  [[ -n "$CURRENT_REVISION" && "$CURRENT_REVISION" != '<no value>' ]] \
    || ops_die "current image has no OCI revision label; cannot verify same-build migration"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  LOCAL_IMAGE="openwebui-transition:pre-ghcr-$STAMP"

  if (( DRY == 1 )); then
    (( PULL == 1 )) && echo "DRY-RUN: pull candidate $GHCR_IMAGE and require OCI revision $CURRENT_REVISION" || echo "DRY-RUN: require locally loaded candidate $GHCR_IMAGE with OCI revision $CURRENT_REVISION"
    echo "DRY-RUN: preserve /app/backend/.webui_secret_key from the running container at $KEY_FILE"
    echo "DRY-RUN: backup-stack.sh --db-only --no-config; docker tag $CURRENT_ID $LOCAL_IMAGE"
    echo "DRY-RUN: recreate only open-webui with $OVERLAY"
    exit 0
  fi

  confirm "Сделать DB backup и переключить только Open WebUI: $CURRENT_IMAGE → $GHCR_IMAGE?" \
    || ops_die "cancelled"

  if (( PULL == 1 )); then
    OPENWEBUI_TRANSITION_IMAGE="$GHCR_IMAGE" \
      $DC $BASE_FILES -f "$OVERLAY" --env-file .env pull open-webui
  else
    docker image inspect "$GHCR_IMAGE" >/dev/null 2>&1 \
      || ops_die "image $GHCR_IMAGE is not loaded locally; transfer/load it first, or pass --pull on a networked host"
  fi

  TARGET_REVISION="$(docker image inspect "$GHCR_IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
  [[ -n "$TARGET_REVISION" && "$TARGET_REVISION" != '<no value>' && "$TARGET_REVISION" == "$CURRENT_REVISION" ]] \
    || ops_die "GHCR candidate $GHCR_IMAGE revision '$TARGET_REVISION' does not match current revision '$CURRENT_REVISION'; no stack/config changes made"

  KEY_TMP="$HERE/.webui_secret_key.check.$$"
  trap 'rm -f -- "${KEY_TMP:-}"' EXIT
  docker cp open-webui:/app/backend/.webui_secret_key "$KEY_TMP" >/dev/null \
    || ops_die "could not read current WEBUI_SECRET_KEY from the running container"
  [[ -s "$KEY_TMP" ]] || ops_die "the current signing key file is empty"
  if [[ -s "$KEY_FILE" ]]; then
    cmp -s "$KEY_FILE" "$KEY_TMP" \
      || ops_die "existing $KEY_FILE differs from the key in the running container; refusing to switch"
    rm -f -- "$KEY_TMP"
  else
    chmod 600 "$KEY_TMP"
    mv -- "$KEY_TMP" "$KEY_FILE"
  fi
  trap - EXIT

  "$HERE/backup-stack.sh" --db-only --no-config
  docker tag "$CURRENT_ID" "$LOCAL_IMAGE"

  umask 077
  {
    printf 'OLD_IMAGE=%q\n' "$CURRENT_IMAGE"
    printf 'OLD_LOCAL_IMAGE=%q\n' "$LOCAL_IMAGE"
    printf 'OLD_IMAGE_ID=%q\n' "$CURRENT_ID"
    printf 'NEW_IMAGE=%q\n' "$GHCR_IMAGE"
  } > "$STATE"
  chmod 600 "$STATE"

  set_compose_image "$GHCR_IMAGE" "$KEY_FILE"
  OPENWEBUI_TRANSITION_IMAGE="$GHCR_IMAGE" \
    $DC $BASE_FILES -f "$OVERLAY" --env-file .env up -d --no-deps --pull never open-webui
  ops_info "Open WebUI switched to $GHCR_IMAGE; DB backup completed; signing key persisted"
  ops_info "Rollback command: ./image-transition.sh rollback"
else
  [[ -s "$STATE" ]] || ops_die "no transition state found; nothing to roll back"
  # State is written by this script and kept mode 600.
  # shellcheck disable=SC1090
  source "$STATE"
  [[ -n "${OLD_LOCAL_IMAGE:-}" && -n "${OLD_IMAGE:-}" ]] || ops_die "invalid transition state"
  docker image inspect "$OLD_LOCAL_IMAGE" >/dev/null 2>&1 || ops_die "saved old image $OLD_LOCAL_IMAGE is missing"
  [[ -s "$KEY_FILE" ]] || ops_die "persisted signing key missing at $KEY_FILE; refusing rollback"

  if (( DRY == 1 )); then
    echo "DRY-RUN: recreate only open-webui with saved image $OLD_LOCAL_IMAGE (original ref: $OLD_IMAGE)"
    echo "DRY-RUN: keep the same PostgreSQL volumes and persisted signing key"
    exit 0
  fi
  confirm "Вернуть Open WebUI на сохранённый образ $OLD_IMAGE?" || ops_die "cancelled"

  set_compose_image "$OLD_LOCAL_IMAGE"
  $DC $BASE_FILES --env-file .env up -d --no-deps --pull never open-webui
  ops_info "Open WebUI rolled back to the exact pre-transition image $OLD_IMAGE"
  ops_info "Transition state and signing-key file were retained for audit and repeat rollback"
fi
