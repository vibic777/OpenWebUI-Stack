#!/usr/bin/env bash
# tika-check.sh — push test documents through the stack's Tika exactly like Open WebUI does and report PASS/FAIL
# per format (Cyrillic, Latin and Chinese markers must be found in the extracted text).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "tika-check.sh — check text extraction of test documents through Apache Tika (Open WebUI Stack)." \
    "tika-check.sh — проверить извлечение текста из тестовых документов через Apache Tika (Open WebUI Stack)."
  cat <<'HELP'
Использование:
  ./tika-check.sh [--dir DIR] [--container NAME] [-h|--help]

  --dir DIR         folder with documents (default: ./tests/fixtures: 10 samples pdf docx xlsx pptx odt ods odp fb2 epub vsdx)
  --container NAME  open-webui container used as the client (default: open-webui)

Each sample contains the markers  КИРИЛЛИЦА-ТЕСТ  LATIN-TEST  中文测试  (in xlsx they are cells).
Own documents: put files into DIR; without markers the script only prints how many characters were extracted.
Exit code 0 = every file returned text (and markers where expected).
HELP
}
DIR="$HERE/tests/fixtures"; CONT=open-webui
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --dir) DIR="$2"; shift 2 ;;
    --container) CONT="$2"; shift 2 ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
[[ -d "$DIR" ]] || ops_die "no such dir: $DIR"
docker inspect -f '{{.State.Running}}' "$CONT" 2>/dev/null | grep -q true || ops_die "container $CONT is not running (Tika needs the Open WebUI Stack)"
ROUTE=openwebui-tika; ROUTE_HEALTH=/version
docker exec "$CONT" curl -fsS -m 8 "http://$ROUTE:9998$ROUTE_HEALTH" >/dev/null || ops_die "extraction route $ROUTE does not answer; inspect its container and openwebui-tika logs"

mime_of() {
  case "${1##*.}" in
    pdf) echo application/pdf ;;
    docx) echo application/vnd.openxmlformats-officedocument.wordprocessingml.document ;;
    xlsx) echo application/vnd.openxmlformats-officedocument.spreadsheetml.sheet ;;
    pptx) echo application/vnd.openxmlformats-officedocument.presentationml.presentation ;;
    odt) echo application/vnd.oasis.opendocument.text ;;
    ods) echo application/vnd.oasis.opendocument.spreadsheet ;;
    odp) echo application/vnd.oasis.opendocument.presentation ;;
    fb2) echo application/x-fictionbook+xml ;;
    epub) echo application/epub+zip ;;
    vsdx) echo application/vnd.ms-visio.drawing ;;
    doc) echo application/msword ;; xls) echo application/vnd.ms-excel ;; ppt) echo application/vnd.ms-powerpoint ;;
    rtf) echo application/rtf ;; txt|md|csv) echo text/plain ;; html|htm) echo text/html ;; xml) echo application/xml ;;
    *) echo application/octet-stream ;;
  esac
}

fail=0; n=0
printf '%-16s %-6s %-6s %-6s %s\n' FILE "RU" "EN" "ZH" CHARS
for f in "$DIR"/*; do
  [[ -f "$f" ]] || continue
  n=$((n+1)); name="$(basename "$f")"
  out="$(docker exec -i "$CONT" curl -s -m 180 -X PUT -H "Content-Type: $(mime_of "$name")" -H 'Accept: application/json' \
        --data-binary @- "http://$ROUTE:9998/tika/json/text" < "$f" || true)"
  # text = tk:content (Tika 4) ; count chars and look for markers without needing python on the host
  txt="$(printf '%s' "$out" | docker exec -i "$CONT" python3 -c '
import sys, json
raw = sys.stdin.read()
try:
    j = json.loads(raw); j = j[0] if isinstance(j, list) else j
    t = j.get("tk:content") or j.get("X-TIKA:content") or ""
except Exception:
    t = ""
print(len(t)); print("КИРИЛЛИЦА-ТЕСТ" in t); print("LATIN-TEST" in t); print("中文测试" in t)' 2>/dev/null || printf '0\nFalse\nFalse\nFalse\n')"
  chars="$(sed -n 1p <<<"$txt")"; ru="$(sed -n 2p <<<"$txt")"; en="$(sed -n 3p <<<"$txt")"; zh="$(sed -n 4p <<<"$txt")"
  mark() { [[ "$1" == True ]] && echo ok || echo -; }
  if [[ "${chars:-0}" -le 0 ]]; then status="FAIL (no text)"; fail=1
  elif [[ "$name" == sample.* && ( "$ru" != True || "$en" != True || "$zh" != True ) ]]; then status="FAIL (marker missing)"; fail=1
  else status="PASS"; fi
  printf '%-16s %-6s %-6s %-6s %s  %s\n' "$name" "$(mark "$ru")" "$(mark "$en")" "$(mark "$zh")" "$chars" "$status"
done
echo; [[ $n -gt 0 ]] || ops_die "no files in $DIR"
if [[ $fail -eq 0 ]]; then
  echo "ALL PASS ($n files)"
else
  echo "SOME FAILED"
  echo "Next: inspect docker logs $ROUTE, openwebui-tika and open-webui; confirm the fixture is digitally readable and TIKA_SERVER_VERSION=4."
  exit 1
fi
