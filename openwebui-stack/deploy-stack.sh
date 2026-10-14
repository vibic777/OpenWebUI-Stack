#!/usr/bin/env bash
# deploy-stack.sh — deploy this Open WebUI stack from scratch.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "deploy-stack.sh — deploy this stack from scratch (works without internet)." \
    "deploy-stack.sh — развернуть этот стек с нуля (работает без интернета)."
  cat <<'HELP'
Использование:
  ./deploy-stack.sh --init                 1) create local runtime configs with generated secrets
                                              (including matching S3 and Qdrant Nginx keys), then set host URLs
  ./deploy-stack.sh [--offline] [--portainer] [--dry-run]     2) start the stack

  --init        create .env (random PostgreSQL / Qdrant / S3 credentials), matching s3.json and Nginx key snippet; never overwrites
  --offline     no internet: do not pull; images must be loaded first (./images-load.sh --from DIR)
  --portainer   also start Portainer (separate compose project)
  --dry-run     show the plan only
  -h, --help    эта справка

New host, no internet, step by step / Новый сервер без интернета:
  ./images-load.sh --from /mnt/usb/images-bundle/<date>
  ./deploy-stack.sh --init          # then edit .env: WEBUI_URL, LMSTUDIO_URL, LMSTUDIO_API_KEY, EMBEDDING_MODEL
  ./deploy-stack.sh --offline --portainer
  ./verify-stack.sh
  (nginx + TLS: see nginx/README.md)
Never runs `down -v`; existing volumes (users, chats) are kept.
HELP
}
INIT=0; OFFLINE=0; PORTAINER=0; DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --init) INIT=1; shift ;;
    --offline) OFFLINE=1; shift ;;
    --portainer) PORTAINER=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
MODE="$(basename "$HERE")"; DC="$(ops_compose)"; cd "$HERE"
command -v docker >/dev/null 2>&1 || ops_die "docker not found"
rand() { head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-28; }
s3_sync() { # write S3 keys from .env into seaweedfs/s3.json
  local ak sk; ak="$(ops_env_get .env S3_ACCESS_KEY)"; sk="$(ops_env_get .env S3_SECRET_KEY)"
  [[ -n "$ak" && -n "$sk" ]] || ops_die "S3_ACCESS_KEY / S3_SECRET_KEY missing in .env"
  [[ -f seaweedfs/s3.json ]] || cp seaweedfs/s3.json.example seaweedfs/s3.json
  sed -i -E "s|(\"accessKey\": *\")[^\"]*|\1${ak}|; s|(\"secretKey\": *\")[^\"]*|\1${sk}|" seaweedfs/s3.json
  chmod 600 seaweedfs/s3.json
}
qdrant_nginx_sync() { # keep optional host-side Nginx snippet aligned with .env
  local key; key="$(ops_env_get .env QDRANT_API_KEY)"
  [[ -n "$key" ]] || ops_die "QDRANT_API_KEY missing in .env"
  [[ -f nginx/qdrant-apikey.conf.example ]] || return 0
  if [[ ! -f nginx/qdrant-apikey.conf ]]; then
    cp nginx/qdrant-apikey.conf.example nginx/qdrant-apikey.conf
  fi
  sed -i -E 's|(proxy_set_header api-key ")[^"]*(";)|\1'"${key}"'\2|' nginx/qdrant-apikey.conf
  chmod 600 nginx/qdrant-apikey.conf
}

if [[ $INIT -eq 1 ]]; then
  [[ -f .env.example ]] || ops_die "no .env.example in $HERE"
  if [[ -f .env ]]; then
    cmp -s .env .env.example \
      || ops_die ".env already exists and differs from the public template: refusing to overwrite"
    rm -- .env
  fi
  cp .env.example .env; chmod 600 .env
  for k in POSTGRES_PASSWORD QDRANT_API_KEY S3_ACCESS_KEY S3_SECRET_KEY; do
    if grep -qiE "^${k}=(change[-_]me|PasswordChangeMe|S3ChangeMe|API_KEY_ChangeMe)$" .env; then sed -i -E "s|^(${k}=).*|\1$(rand)|" .env; fi
  done
  [[ -f seaweedfs/s3.json.example ]] && s3_sync
  qdrant_nginx_sync
  ops_info "Review .env and set WEBUI_URL, LMSTUDIO_URL, LMSTUDIO_API_KEY, and EMBEDDING_MODEL for your host"
  ops_info "created $HERE/.env with generated secrets (mode 600)"
  ops_info "NOW EDIT .env: WEBUI_URL (https://<host or IP>), LMSTUDIO_URL (http://<inference>:1234/v1), EMBEDDING_MODEL"
  ops_info "then: ./deploy-stack.sh$([[ $OFFLINE -eq 1 ]] && echo ' --offline')"
  exit 0
fi

[[ -f .env ]] || ops_die "no .env: run ./deploy-stack.sh --init first"
if grep -qiE "CHANGE[-_]ME|IP_ADDRESS|API_KEY_ChangeMe|S3ChangeMe|PasswordChangeMe" .env; then
  grep -niE "CHANGE[-_]ME|IP_ADDRESS|API_KEY_ChangeMe|S3ChangeMe|PasswordChangeMe" .env | sed -E 's/=.*/=<placeholder>/' >&2
  ops_die "placeholders left in .env (lines above): set real values (WEBUI_URL, LMSTUDIO_URL, ...)"
fi
if [[ -f seaweedfs/s3.json.example ]]; then
  if [[ -f seaweedfs/s3.json ]]; then
    ak="$(ops_env_get .env S3_ACCESS_KEY)"; sk="$(ops_env_get .env S3_SECRET_KEY)"
    grep -q "\"accessKey\": *\"${ak}\"" seaweedfs/s3.json && grep -q "\"secretKey\": *\"${sk}\"" seaweedfs/s3.json \
      || ops_die "seaweedfs/s3.json does not match S3_ACCESS_KEY/S3_SECRET_KEY in .env (fix .env or delete s3.json and re-run: it will be regenerated)"
  else
    s3_sync; ops_info "seaweedfs/s3.json created from .env"
  fi
fi
if [[ -f nginx/qdrant-apikey.conf ]]; then
  qk="$(ops_env_get .env QDRANT_API_KEY)"
  grep -Fq "proxy_set_header api-key \"${qk}\";" nginx/qdrant-apikey.conf \
    || ops_die "nginx/qdrant-apikey.conf does not match QDRANT_API_KEY in .env (delete it and re-run --init to regenerate)"
fi
if grep -q policy.env docker-compose.yml && [[ ! -f policy.env ]]; then : > policy.env; ops_info "created empty policy.env (edit policy.env if overrides are needed)"; fi
$DC -f docker-compose.yml --env-file .env config >/dev/null

mapfile -t images < <($DC -f docker-compose.yml --env-file .env config --images | awk 'NF' | sort -u)
(( ${#images[@]} > 0 )) || ops_die "compose returned no images"
if [[ $DRY -eq 1 ]]; then printf 'PLAN: deploy %s; images:\n' "$MODE"; printf '  %s\n' "${images[@]}"; exit 0; fi
for image in "${images[@]}"; do
  if (( OFFLINE )); then
    docker image inspect "$image" >/dev/null 2>&1 || ops_die "offline: image missing: $image  (run ./images-load.sh --from DIR)"
    echo "image present: $image"; continue
  fi
  pulled=0
  for attempt in 1 2 3; do
    echo "pull $image (attempt $attempt/3)"
    if docker pull "$image"; then pulled=1; break; fi
    sleep $((attempt * 5))
  done
  if (( ! pulled )); then
    docker image inspect "$image" >/dev/null 2>&1 || ops_die "cannot pull and not present locally: $image (use --offline after ./images-load.sh)"
    echo "WARNING: pull failed, using the local image $image"
  fi
done
UP=(-f docker-compose.yml --env-file .env up -d --wait --wait-timeout 240 --pull never)
$DC "${UP[@]}"
$DC -f docker-compose.yml --env-file .env ps
if (( PORTAINER )); then
  [[ -f docker-compose.portainer.yml ]] || ops_die "no docker-compose.portainer.yml"
  $DC -f docker-compose.portainer.yml --env-file .env up -d --pull never
fi
ops_info "$MODE stack is up. Check: ./verify-stack.sh"
if [[ "$MODE" == openwebui-stack ]]; then ops_info "Rerank is OFF by default. Download bge-reranker-v2-m3-Q8_0.gguf from Hugging Face, save as rerank/models/model.gguf, then run ./enable-rerank.sh"; fi


