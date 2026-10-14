#!/usr/bin/env bash
# Run Open WebUI Stack health, integration, and optional authenticated RAG end-to-end checks.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  cat <<'HELP'
Полная проверка стека Open WebUI и интеграций.
Использование:
  ./full-test.sh [--all] [--reranker] [--ask-password] [--list-models] [--e2e-rag]

По умолчанию проверяет базовое здоровье стека без проверки ключей.
--reranker добавляет проверку образа и включённого сервиса reranker.
--all выполняет все интеграционные проверки, включая ключи и reranker.
Проверка Nginx читает конфигурацию через nginx -T и посылает синтетическую
2-МБ пробу; конфиг не меняется и reload не выполняется. Изменять лимит можно
отдельно через nginx-upload-limit.sh set SIZE (проверка nginx -t, затем reload).
--list-models получает список моделей через API Open WebUI; нужен ключ администратора.
--e2e-rag проверяет DOCX -> Tika -> embeddings/Qdrant -> hybrid retrieval ->
ответ чата по файлу -> удаление тестового файла. Также печатает модели и
использует OPENWEBUI_E2E_MODEL; без него берёт первую доступную модель.
Ключ Open WebUI задаётся через OPENWEBUI_API_KEY или OPENWEBUI_API_KEY_FILE.
Ключ провайдера модели скрипту не нужен: его использует сам Open WebUI.
Подробности и получение ключа: RAG-E2E-HELP.md. Reranker обязателен, если включён overlay.
HELP
}
ASK=0
E2E_RAG=0
LIST_MODELS=0
CHECK_MODE=base
CHECK_RERANK=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --ask-password) ASK=1; shift ;;
    --list-models) LIST_MODELS=1; shift ;;
    --e2e-rag) E2E_RAG=1; shift ;;
    --reranker) CHECK_RERANK=1; shift ;;
    --all) CHECK_MODE=all; CHECK_RERANK=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done

RESULTS=(); FAILED=0; SKIPPED=0
run_suite() {
  local label="$1"; shift
  echo; echo "===== $label ====="
  if "$@"; then
    RESULTS+=("PASS  $label")
  else
    RESULTS+=("FAIL  $label")
    FAILED=$((FAILED + 1))
  fi
}

run_suite "deployed Compose/image report" "$HERE/show-stack-deployment.sh"
run_suite "Nginx: лимит и upload-маршрут через HTTPS" "$HERE/nginx-upload-limit.sh" get --probe-size 2m
VERIFY_ARGS=(); [[ $ASK -eq 1 ]] && VERIFY_ARGS+=(--ask-password)
[[ "$CHECK_MODE" == all ]] && VERIFY_ARGS+=(--all)
[[ "$CHECK_RERANK" -eq 1 && "$CHECK_MODE" != all ]] && VERIFY_ARGS+=(--reranker)
run_suite "stack health and selected checks ($CHECK_MODE)" "$HERE/verify-stack.sh" "${VERIFY_ARGS[@]}"
run_suite "PostgreSQL connection/schema" "$HERE/check-postgres.sh"
run_suite "Valkey PING" "$HERE/check-valkey.sh"
run_suite "LM Studio embeddings" "$HERE/check-embeddings.sh"
run_suite "Qdrant CRUD from Open WebUI" "$HERE/check-qdrant.sh"
run_suite "SeaweedFS S3 CRUD from Open WebUI" "$HERE/check-seaweedfs.sh"
run_suite "Tika document extraction" "$HERE/tika-check.sh"
if [[ $LIST_MODELS -eq 1 || $E2E_RAG -eq 1 ]]; then
  run_suite "список моделей Open WebUI (через API)" "$HERE/list-models.sh"
fi
if [[ $E2E_RAG -eq 1 && -z "${OPENWEBUI_E2E_MODEL:-}" && -t 0 ]]; then
  read -r -p "Введите ID чат-модели из списка (Enter — выбрать первую доступную автоматически): " selected_model
  if [[ -n "$selected_model" ]]; then export OPENWEBUI_E2E_MODEL="$selected_model"; fi
fi
if [[ $E2E_RAG -eq 1 ]]; then
  run_suite "Open WebUI authenticated upload-to-RAG end-to-end" "$HERE/check-e2e-rag.sh"
else
  RESULTS+=("SKIP  authenticated Open WebUI RAG end-to-end (use --e2e-rag)")
  SKIPPED=$((SKIPPED + 1))
fi
if [[ "$CHECK_RERANK" -eq 1 ]] && ops_rerank_on "$HERE"; then
  run_suite "external reranker functional probe" "$HERE/check-rerank.sh"
else
  RESULTS+=("SKIP  optional reranker functional probe (use --reranker or --all)")
  SKIPPED=$((SKIPPED + 1))
fi

echo; echo "===== FULL TEST SUMMARY ====="
printf '%s\n' "${RESULTS[@]}"
if [[ $FAILED -eq 0 ]]; then
  echo "ALL PASS ($(( ${#RESULTS[@]} - SKIPPED )) suites; $SKIPPED optional skipped)"
  exit 0
fi
echo "FAILED: $FAILED suite(s); use the FAIL diagnostics above to locate the layer"
exit 1
