#!/usr/bin/env bash
# Enable CPU reranker (bge-reranker-v2-m3 GGUF) for Open WebUI A/B tests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
enable-rerank.sh — включить CPU reranker и Compose overlay для Open WebUI.
Команда запускает сервисы и создаёт marker .rerank-enabled, чтобы start/update/stop
учитывали слой. Модель и конфигурация должны быть подготовлены заранее.

Аргументы: не принимает параметры, кроме -h/--help.
Требование: отдельно скачайте `bge-reranker-v2-m3-Q8_0.gguf` с Hugging Face
`gpustack/bge-reranker-v2-m3-GGUF` и сохраните как `rerank/models/model.gguf`.
Ссылка и сведения о файле: `rerank/models/SOURCE.txt`. Для проверки: ./check-rerank.sh.

Примеры:
  ./enable-rerank.sh && ./check-rerank.sh
  ./verify-stack.sh && ./enable-rerank.sh
HELP
  exit 0
fi
(( $# == 0 )) || { echo "Аргументы не поддерживаются; используйте --help" >&2; exit 2; }
test -f rerank/models/model.gguf || { echo "Missing rerank/models/model.gguf. Download bge-reranker-v2-m3-Q8_0.gguf from https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF and see rerank/models/SOURCE.txt"; exit 1; }
docker compose -f docker-compose.rerank.yml up -d
docker compose -f docker-compose.yml -f docker-compose.rerank-owui.yml up -d
touch .rerank-enabled   # marker: start/update/stop-stack.sh keep the reranker overlay
echo "Rerank ON. Probe: ./rerank/test-rerank.sh"
