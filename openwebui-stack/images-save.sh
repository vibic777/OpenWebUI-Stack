#!/usr/bin/env bash
# images-save.sh — run on a machine WITH internet: pull stock images of THIS stack and save them as tar files
# for an air-gapped server.  / Запускать на машине С интернетом: скачать образы и сохранить в tar.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "images-save.sh — pull stock images of this stack and save to tar (for air-gapped hosts)." \
    "images-save.sh — скачать стандартные образы этого стека и сохранить в tar (для сервера без интернета)."
  cat <<'HELP'
Использование:
  ./images-save.sh [--out DIR] [--portainer] [--rerank] [--no-pull] [--list]

  --out DIR    output dir (default: ./images-bundle/<date>)
  --portainer  also the Portainer image
  --rerank     also the optional llama.cpp reranker image
  --no-pull    do not pull, save what is already local
  --list       only print the image names this stack needs, then exit

Result: DIR/*.tar + images.txt + SHA256SUMS. Copy DIR to the offline host, then there: ./images-load.sh --from DIR
Images are referenced by tag (no @sha256): after `docker load` compose finds them locally.
To use a newer version: bring the new image, load it, override the variable in .env
(OPENWEBUI_IMAGE=..., TIKA_IMAGE=..., ...) or keep the same tag, then ./update-stack.sh --offline.
This bundle is the full set for this stack and can also serve migrations from smaller stacks.
HELP
}
RERANK=0; PORTAINER=0; OUT=""; PULL=1; LIST=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --rerank) RERANK=1; shift ;;
    --portainer) PORTAINER=1; shift ;;
    --out) OUT="$2"; shift 2 ;;
    --no-pull) PULL=0; shift ;;
    --list) LIST=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
DC="$(ops_compose)"; OUT="${OUT:-$HERE/images-bundle/$(date +%Y%m%d)}"
list=()
add_from() { # compose file
  [[ -f "$HERE/$1" ]] || return 0
  # .env may be absent on the build machine: dummy values are enough to resolve image names
  while IFS= read -r i; do [[ -n "$i" ]] && list+=("$i"); done < <(cd "$HERE" && \
    POSTGRES_PASSWORD=x POSTGRES_USER=x POSTGRES_DB=x WEBUI_URL=x QDRANT_API_KEY=x S3_ACCESS_KEY=x S3_SECRET_KEY=x \
    S3_BUCKET_NAME=x LMSTUDIO_URL=x LMSTUDIO_API_KEY=x EMBEDDING_MODEL=x $DC -f "$1" config --images)
}
add_from docker-compose.yml
[[ $RERANK -eq 1 ]]    && add_from docker-compose.rerank.yml
[[ $PORTAINER -eq 1 ]] && add_from docker-compose.portainer.yml
mapfile -t list < <(printf '%s\n' "${list[@]}" | sort -u)
[[ ${#list[@]} -gt 0 ]] || ops_die "no images found"
if [[ $LIST -eq 1 ]]; then printf '%s
' "${list[@]}"; exit 0; fi
mkdir -p "$OUT"; : > "$OUT/images.txt"
for img in "${list[@]}"; do
  if [[ $PULL -eq 1 ]]; then ops_info "pull $img"; docker pull "$img"; fi
  docker image inspect "$img" >/dev/null 2>&1 || ops_die "image not present locally: $img"
  f="$(echo "$img" | tr '/:@' '___').tar"
  ops_info "save $img -> $f"
  docker save -o "$OUT/$f" "$img"
  echo "$img  $f" >> "$OUT/images.txt"
done
( cd "$OUT" && sha256sum ./*.tar > SHA256SUMS )
ops_info "done: $OUT ($(du -sh "$OUT" | cut -f1)); ${#list[@]} images"
