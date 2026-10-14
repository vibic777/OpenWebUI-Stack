#!/usr/bin/env bash
# Read-only report of the Compose metadata and actual image references on running stack containers.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
Использование:
  ./show-stack-deployment.sh [-h|--help]

Только читает Docker metadata: Compose-проект, активные Compose-файлы,
контейнеры и образы (ссылки, ID, локальные теги/digest, архитектура).
Не меняет стек. Docker не хранит надёжную историю, откуда образ скачивали.
HELP
  exit 0
fi
(( $# == 0 )) || ops_die "скрипт не принимает аргументы (используйте --help)"
PRIMARY="open-webui"
docker inspect "$PRIMARY" >/dev/null 2>&1 || ops_die "container $PRIMARY not found; start the stack or check Docker context/permissions"
get_label() { docker inspect --format "{{ index .Config.Labels \"$2\" }}" "$1" 2>/dev/null || true; }
project="$(get_label "$PRIMARY" com.docker.compose.project)"
[[ -n "$project" && "$project" != '<no value>' ]] || ops_die "container $PRIMARY has no Compose project label (it may not have been started by Compose)"
echo "== Deployed Open WebUI stack =="
echo "Docker context: $(docker context show 2>/dev/null || echo unknown)"
echo "Compose project: $project"
echo
echo "Compose metadata recorded on running container:"
for label in com.docker.compose.project.working_dir com.docker.compose.project.config_files; do
  value="$(get_label "$PRIMARY" "$label")"
  [[ -n "$value" && "$value" != '<no value>' ]] && echo "  $label: $value" || echo "  $label: unavailable"
done
echo
echo "Containers and local image identities:"
ids="$(docker ps -aq --filter "label=com.docker.compose.project=$project")"
# Reranker is an independently named Compose project but is part of the Open WebUI Stack integration.
rerank_id="$(docker inspect -f '{{.Id}}' openwebui-rerank 2>/dev/null || true)"
[[ -n "$rerank_id" ]] && ids="$(printf '%s\n%s' "$ids" "$rerank_id" | awk 'NF && !seen[$0]++')"
[[ -n "$ids" ]] || ops_die "no containers found for Compose project $project"
while IFS= read -r id; do
  [[ -n "$id" ]] || continue
  name="$(docker inspect -f '{{.Name}}' "$id")"
  name="${name#/}"
  state="$(docker inspect -f '{{.State.Status}}' "$id")"
  image_ref="$(docker inspect -f '{{.Config.Image}}' "$id")"
  image_id="$(docker inspect -f '{{.Image}}' "$id")"
  service="$(get_label "$id" com.docker.compose.service)"
  cproject="$(get_label "$id" com.docker.compose.project)"
  echo "- $name (service=${service:-unknown}; project=${cproject:-standalone}; state=$state)"
  echo "    configured image: $image_ref"
  image_meta="$(docker image inspect --format '{{json .RepoTags}}|{{json .RepoDigests}}|{{.Created}}|{{.Os}}/{{.Architecture}}' "$image_id" 2>/dev/null || true)"
  if [[ -n "$image_meta" ]]; then
    IFS='|' read -r tags digests created platform <<<"$image_meta"
    echo "    local image ID: $image_id"
    echo "    local tags: $tags"
    echo "    registry digests: $digests"
    echo "    created: $created; platform: $platform"
  else
    echo "    local image metadata: unavailable (image may have been removed)"
  fi
done <<<"$ids"
echo
echo "Image source means the configured repository:tag above; Docker does not retain a reliable registry download history."
echo "RepoDigests identifies the content digest when the image was pulled or preserved with that metadata."
