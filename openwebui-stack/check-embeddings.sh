#!/usr/bin/env bash
# Probe the configured OpenAI-compatible embedding endpoint from Open WebUI itself.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
check-embeddings.sh — проверить доступность embedding-модели из Open WebUI.
Проба использует URL и параметры модели из текущей конфигурации; содержимое БД не меняет.

Аргументы: не принимает позиционных аргументов или параметров, кроме -h/--help.
Требования: запущенный контейнер open-webui и настроенный embedding endpoint.

Примеры:
  ./check-embeddings.sh       # выполнить интеграционную пробу
  cd /path/to/openwebui-stack && ./check-embeddings.sh
HELP
  exit 0
fi
(( $# == 0 )) || ops_die "аргументы не поддерживаются; используйте --help"
docker inspect -f '{{.State.Running}}' open-webui 2>/dev/null | grep -q true \
  || ops_die "open-webui is not running; start the Open WebUI Stack first"
docker exec -i open-webui python3 - <<'PY'
import json, math, os, sys, urllib.error, urllib.request

base = os.environ.get("RAG_OPENAI_API_BASE_URL", "").rstrip("/")
model = os.environ.get("RAG_EMBEDDING_MODEL", "")
key = os.environ.get("RAG_OPENAI_API_KEY", "")
if not base or not model:
    print("FAIL  embedding configuration missing; check RAG_OPENAI_API_BASE_URL and RAG_EMBEDDING_MODEL in Compose")
    sys.exit(1)
url = base + "/embeddings"
body = json.dumps({"model": model, "input": "Open WebUI Stack integration probe"}).encode()
headers = {"Content-Type": "application/json"}
if key:
    headers["Authorization"] = "Bearer " + key
try:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read())
    vectors = result.get("data", [])
    vector = vectors[0].get("embedding", []) if vectors else []
    valid = bool(vector) and all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector)
    if not valid:
        raise ValueError("response has no valid numeric embedding vector")
    print(f"PASS  LM Studio embedding API via Open WebUI network: model={model}; dimensions={len(vector)}")
except urllib.error.HTTPError as exc:
    print(f"FAIL  embedding API HTTP {exc.code}; check LMSTUDIO_URL, model id '{model}', model loaded in LM Studio, and API key")
    sys.exit(1)
except Exception as exc:
    print(f"FAIL  embedding request to {url}: {type(exc).__name__}: {exc}; check LM Studio reachability/model configuration")
    sys.exit(1)
PY
