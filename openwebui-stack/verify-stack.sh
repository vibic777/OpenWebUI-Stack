#!/usr/bin/env bash
# verify-stack.sh — smoke-check that THIS stack is healthy. Exit code 0 = all PASS.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
set +e  # retain the per-check FAIL output instead of aborting on the first unavailable service

usage() {
  ops_print_bilingual_header \
    "verify-stack.sh — health check of this stack (containers, DB, Qdrant, S3, Tika, UI)." \
    "verify-stack.sh — проверка здоровья этого стека (контейнеры, БД, Qdrant, S3, Tika, UI)."
  cat <<'HELP'
Использование:
  ./verify-stack.sh [--all] [--ask-password]

Базовые сервисы и автоматически обнаруженный включённый слой reranker
проверяются без флагов. Выключенный reranker получает статус SKIP.

Включённый reranker проверяется также коротким функциональным запросом.
--all дополнительно проверяет БД, S3, Qdrant и прочие интеграционные настройки.
DB password: $PGPASSWORD, or --ask-password, or POSTGRES_PASSWORD from .env.
HELP
}
MODE=base; ASK=0; CHECK_RERANK=1
while [[ $# -gt 0 ]]; do case "$1" in -h|--help) usage; exit 0 ;; --ask-password) ASK=1; shift ;; --reranker) CHECK_RERANK=1; shift ;; --all) MODE=all; CHECK_RERANK=1; shift ;; *) ops_die "unknown arg: $1" ;; esac; done
DIRNAME="$(basename "$HERE")"; ENVF="$HERE/.env"; FAIL=0
pass() { echo "PASS  $*"; }; fail() { echo "FAIL  $*"; FAIL=1; }
echo "== verify $DIRNAME ($MODE) =="
expected="open-webui openwebui-postgres openwebui-qdrant openwebui-valkey openwebui-seaweedfs"
HAS_TIKA=0
if grep -Eq '^  tika:' "$HERE/docker-compose.yml"; then
  HAS_TIKA=1
  expected="$expected openwebui-tika"
fi
for c in $expected; do
  st="$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' "$c" 2>/dev/null || echo missing)"
  case "$st" in running/healthy|running/-) pass "container $c ($st)" ;; *) fail "container $c ($st)" ;; esac
done
h="$(docker exec open-webui curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health 2>/dev/null)"
[[ "$h" == 200 ]] && pass "open-webui /health = 200" || fail "open-webui /health = ${h:-none}"
webui_env="$(docker inspect open-webui --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null)"
runtime_env_has() { grep -q "^$1=." <<<"$webui_env"; }
if [[ "$MODE" == all ]]; then
DBN="$(ops_env_get "$ENVF" POSTGRES_DB)"; DBU="$(ops_env_get "$ENVF" POSTGRES_USER)"
if [[ $ASK -eq 1 ]]; then read -r -s -p "PostgreSQL password: " PGPASSWORD; echo; fi
PGPASSWORD="${PGPASSWORD:-$(ops_env_get "$ENVF" POSTGRES_PASSWORD)}"; export PGPASSWORD
QK="$(ops_env_get "$ENVF" QDRANT_API_KEY)"
c="$(docker exec -e PGPASSWORD openwebui-postgres psql -U "$DBU" -d "$DBN" -Atc \
  "select 'users='||(select count(*) from \"user\")||' chats='||(select count(*) from chat)||' groups='||(select count(*) from \"group\")" 2>/dev/null)"
[[ -n "$c" ]] && pass "postgres: $c" || fail "postgres query failed (db=$DBN user=$DBU)"
vk="$(docker exec openwebui-valkey sh -c 'valkey-cli ping 2>/dev/null || redis-cli ping 2>/dev/null' 2>/dev/null | tail -1 | tr -d '\r')"
[[ "${vk,,}" == pong ]] && pass "valkey PING" || fail "valkey PING failed; inspect openwebui-valkey logs and port 6379"
env_value() { sed -n "s/^$1=//p" <<<"$webui_env" | tail -1; }
check_env() {
  local name="$1" expected_value="$2" hint="$3"
  if [[ "$(env_value "$name")" == "$expected_value" && -n "$expected_value" ]]; then
    pass "Open WebUI config $name"
  else
    fail "Open WebUI config $name mismatch; $hint"
  fi
}
check_env VECTOR_DB qdrant "set VECTOR_DB=qdrant in docker-compose.yml"
check_env QDRANT_URI http://openwebui-qdrant:6333 "check the Qdrant service name/network in docker-compose.yml"
check_env STORAGE_PROVIDER s3 "set STORAGE_PROVIDER=s3 and verify S3 config"
check_env S3_ENDPOINT_URL http://openwebui-seaweedfs:8333 "check SeaweedFS service name/network"
check_env S3_BUCKET_NAME "$(ops_env_get "$ENVF" S3_BUCKET_NAME)" "compare S3_BUCKET_NAME in .env and Open WebUI compose environment"
[[ "$(env_value S3_ACCESS_KEY_ID)" == "$(ops_env_get "$ENVF" S3_ACCESS_KEY)" && -n "$(env_value S3_ACCESS_KEY_ID)" ]] \
  && pass "Open WebUI S3 access key matches .env" \
  || fail "Open WebUI S3 access key differs from .env; check S3_ACCESS_KEY mapping (value hidden)"
[[ "$(env_value S3_SECRET_ACCESS_KEY)" == "$(ops_env_get "$ENVF" S3_SECRET_KEY)" && -n "$(env_value S3_SECRET_ACCESS_KEY)" ]] \
  && pass "Open WebUI S3 secret matches .env" \
  || fail "Open WebUI S3 secret differs from .env; check S3_SECRET_KEY mapping (value hidden)"
q="$(docker exec open-webui python3 -c "
import urllib.request,json,sys
r=urllib.request.Request('http://openwebui-qdrant:6333/collections',headers={'api-key':'$QK'} if '$QK' else {})
print(len(json.load(urllib.request.urlopen(r,timeout=8))['result']['collections']))" 2>/dev/null)"
[[ -n "$q" ]] && pass "qdrant API ok ($q collections)" || fail "qdrant API failed (key?)"
sc="$(docker exec open-webui python3 -c "
import urllib.request,urllib.error
try: r=urllib.request.urlopen('http://openwebui-seaweedfs:8333/',timeout=8); print(r.status)
except urllib.error.HTTPError as e: print(e.code)
except Exception as e: print('ERR')" 2>/dev/null)"
case "$sc" in 200|403) pass "s3 endpoint answers ($sc)" ;; *) fail "s3 endpoint: ${sc:-none}" ;; esac
if [[ "$HAS_TIKA" -eq 1 ]]; then
  t="$(docker exec open-webui curl -s -m 8 http://openwebui-tika:9998/version 2>/dev/null)"
  [[ -n "$t" ]] && pass "tika: $t" || fail "tika not answering"
  check_env CONTENT_EXTRACTION_ENGINE tika "set CONTENT_EXTRACTION_ENGINE=tika"
  check_env TIKA_SERVER_URL http://openwebui-tika:9998 "check the Tika service name/network in docker-compose.yml"
  tv="$(grep -c '^TIKA_SERVER_VERSION=4$' <<<"$webui_env" || true)"
  [[ "$tv" == 1 ]] && pass "TIKA_SERVER_VERSION=4 set" || fail "TIKA_SERVER_VERSION=4 missing (Tika 4 needs it)"
fi
fi
if [[ "$CHECK_RERANK" -eq 1 ]]; then
  if ops_rerank_on "$HERE"; then
    image="$(ops_env_get "$ENVF" RERANK_IMAGE)"
    if [[ -z "$image" && -f "$HERE/docker-compose.rerank.yml" ]]; then dc="$(ops_compose)"; image="$(cd "$HERE" && $dc -f docker-compose.rerank.yml --env-file .env config --images 2>/dev/null | head -n 1)"; fi
    if [[ -n "$image" ]] && docker image inspect "$image" >/dev/null 2>&1; then pass "reranker image present: $image"; else fail "reranker image missing: ${image:-unset}"; fi
    st="$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' openwebui-rerank 2>/dev/null || echo missing)"
    case "$st" in running/healthy|running/-) pass "reranker container ($st)" ;; *) fail "reranker container ($st)" ;; esac
    grep -qx 'RAG_RERANKING_ENGINE=external' <<<"$webui_env" && pass "Open WebUI reranker engine configured" || fail "Open WebUI reranker engine is not external"
    grep -qx 'RAG_EXTERNAL_RERANKER_URL=http://openwebui-rerank:8080/v1/rerank' <<<"$webui_env" && pass "Open WebUI reranker URL configured" || fail "Open WebUI reranker URL mismatch"
    if [[ "$st" == running/healthy || "$st" == running/- ]]; then
      if bash "$HERE/check-rerank.sh"; then pass "reranker functional probe"; else fail "reranker functional probe failed; see output above"; fi
    fi
  else echo "SKIP  reranker layer is disabled"; fi
fi
if command -v curl >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ':443 '; then
  n="$(curl -sk -m 8 -o /dev/null -w '%{http_code}' https://127.0.0.1/ 2>/dev/null)"
  [[ "$n" == 200 ]] && pass "nginx https://127.0.0.1/ = 200" || fail "nginx https = ${n:-none}"
fi
echo; [[ $FAIL -eq 0 ]] && echo "ALL PASS" || echo "SOME CHECKS FAILED"; exit $FAIL
