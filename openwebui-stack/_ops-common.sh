#!/usr/bin/env bash
# Shared helpers for the Open WebUI Stack scripts.
# Every script lives INSIDE its stack folder and works only on that folder's stack.
set -euo pipefail

ops_die() { echo "ERROR: $*" >&2; exit 1; }
ops_info() { echo "[*] $*"; }

ops_compose() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
  else
    ops_die "docker compose not found"
  fi
}

ops_print_bilingual_header() {
  echo "$1"
  echo "$2"
  echo
}

# ops_env_get FILE KEY -> value of KEY from .env (no quotes, no CR)
ops_env_get() {
  local f="$1" k="$2"
  [[ -f "$f" ]] || return 0
  { grep -E "^${k}=" "$f" || true; } | tail -1 | cut -d= -f2- | tr -d '\r' \
    | sed -e "s/^[\"']//" -e "s/[\"']\$//"
}

# Rerank exists only in openwebui-stack/. Marker .rerank-enabled is created by enable-rerank.sh.
ops_rerank_on() { [[ -f "$1/.rerank-enabled" && -f "$1/docker-compose.rerank-owui.yml" ]]; }

# ops_files DIR -> compose -f arguments for the main stack and enabled overlays.
ops_files() {
  local out="-f docker-compose.yml"
  # Compose references policy.env via env_file: it must exist (empty is fine)
  if grep -q 'policy.env' "$1/docker-compose.yml" 2>/dev/null && [[ ! -f "$1/policy.env" ]]; then : > "$1/policy.env"; fi
  if ops_rerank_on "$1"; then out="$out -f docker-compose.rerank-owui.yml"; fi
  echo "$out"
}

# ops_missing_images DC DIR -> images referenced by compose that are not present locally
ops_missing_images() {
  local dc="$1" dir="$2" img
  ( cd "$dir" && $dc $(ops_files "$dir") --env-file .env config --images ) 2>/dev/null | awk 'NF' | sort -u | while read -r img; do
    docker image inspect "$img" >/dev/null 2>&1 || echo "$img"
  done
}

# ops_container_volume CONTAINER MOUNT_DEST -> exact docker volume name (from mounts, no name guessing)
ops_container_volume() {
  docker inspect "$1" --format "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" 2>/dev/null
}
