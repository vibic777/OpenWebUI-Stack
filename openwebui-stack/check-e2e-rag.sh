#!/usr/bin/env bash
# Upload a synthetic DOCX, exercise extraction/embeddings/vector+hybrid retrieval and chat, then clean it up.
# Requires an administrator API key; temporary file and file-{id} vectors are deleted by ID.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
Использование:
  ./check-e2e-rag.sh [-h|--help]

Сквозная проверка: временный DOCX -> Tika -> embeddings/Qdrant -> hybrid
retrieval -> ответ выбранной чат-модели -> удаление тестового файла.
Нужен admin API-ключ Open WebUI: OPENWEBUI_API_KEY либо
OPENWEBUI_API_KEY_FILE. Модель задаётся через OPENWEBUI_E2E_MODEL.
Подробно: ./RAG-E2E-HELP.md. Ключ провайдера модели не нужен.
HELP
  exit 0
fi
ENVF="$HERE/.env"
API_KEY="${OPENWEBUI_API_KEY:-${WEBUI_API_KEY:-}}"
if [[ -z "$API_KEY" ]]; then API_KEY="$(ops_env_get "$ENVF" OPENWEBUI_API_KEY)"; fi
if [[ -z "$API_KEY" ]]; then
  KEY_FILE="${OPENWEBUI_API_KEY_FILE:-$(ops_env_get "$ENVF" OPENWEBUI_API_KEY_FILE)}"
  if [[ -n "$KEY_FILE" ]]; then
    [[ -r "$KEY_FILE" ]] || ops_die "API key file is not readable: $KEY_FILE"
    API_KEY="$(tr -d '\r\n' < "$KEY_FILE")"
  fi
fi
[[ -n "$API_KEY" ]] || ops_die "укажите OPENWEBUI_API_KEY либо OPENWEBUI_API_KEY_FILE (см. RAG-E2E-HELP.md)"
BASE_URL="$(ops_env_get "$ENVF" WEBUI_URL)"
[[ -n "$BASE_URL" && "$BASE_URL" != https://CHANGE-ME-HOST ]] || ops_die "set WEBUI_URL in $ENVF to a URL reachable from this host"
MODEL="${OPENWEBUI_E2E_MODEL:-$(ops_env_get "$ENVF" OPENWEBUI_E2E_MODEL)}"
export OPENWEBUI_API_KEY="$API_KEY" OPENWEBUI_BASE_URL="${BASE_URL%/}" OPENWEBUI_E2E_MODEL="$MODEL"
if ops_rerank_on "$HERE"; then export OWUI_RERANK_EXPECTED=1; else export OWUI_RERANK_EXPECTED=0; fi
export OWUI_TIKA_URL_EXPECTED=http://openwebui-tika:9998
python3 - <<'PY'
import io, json, os, sys, time, urllib.error, urllib.parse, urllib.request, uuid, zipfile

base = os.environ["OPENWEBUI_BASE_URL"].rstrip("/")
headers = {"Authorization": "Bearer " + os.environ["OPENWEBUI_API_KEY"], "Accept": "application/json"}
marker = "OWUI_RAG_E2E_" + uuid.uuid4().hex
filename = "openwebui-rag-e2e-" + uuid.uuid4().hex[:12] + ".docx"
content = ("Open WebUI Stack RAG integration diagnostic.\n"
           "The unique diagnostic code is " + marker + ".\n"
           "This text must be retrievable by searching for its unique diagnostic code.\n")
file_id = None
failed = False

def request(path, method="GET", data=None, extra_headers=None, timeout=60):
    h = dict(headers)
    if extra_headers: h.update(extra_headers)
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        if raw and "json" in ctype.lower():
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError as exc:
                preview = raw[:240].decode("utf-8", "replace").replace("\n", " ")
                raise RuntimeError(f"{method} {path} returned invalid JSON (Content-Type={ctype}); response starts: {preview!r}") from exc
        if raw and ("text/html" in ctype.lower() or raw.lstrip().startswith(b"<")):
            preview = raw[:240].decode("utf-8", "replace").replace("\n", " ")
            raise RuntimeError(f"{method} {path} returned HTML instead of API JSON (Content-Type={ctype}); check WEBUI_URL in .env, reverse-proxy routing, and API path; response starts: {preview!r}")
        return resp.status, raw

def mark(label, ok, detail=""):
    global failed
    print(("PASS  " if ok else "FAIL  ") + label + (": " + str(detail) if detail else ""), flush=True)
    failed |= not ok

def contains(value, needle):
    if isinstance(value, str): return needle in value
    if isinstance(value, dict): return any(contains(v, needle) for v in value.values())
    if isinstance(value, (list, tuple)): return any(contains(v, needle) for v in value)
    return False

try:
    # Admin endpoint verifies effective settings, not just that a hybrid query was requested.
    _, config = request("/api/v1/retrieval/config")
    config_ok = isinstance(config, dict) and config.get("status") is True
    mark("read active RAG configuration", config_ok)
    if not config_ok: raise RuntimeError("RAG config endpoint returned an unexpected response")
    extraction_engine = config.get("CONTENT_EXTRACTION_ENGINE") or ""
    tika_url = (config.get("TIKA_SERVER_URL") or "").rstrip("/")
    mark("Tika is the active extraction engine", extraction_engine == "tika", "CONTENT_EXTRACTION_ENGINE=" + str(extraction_engine or "unset"))
    expected_tika_url = os.environ.get("OWUI_TIKA_URL_EXPECTED", "http://openwebui-tika:9998")
    mark("Open WebUI points to the Apache Tika extraction route", tika_url == expected_tika_url,
         "TIKA_SERVER_URL=" + str(tika_url or "unset") + "; expected=" + expected_tika_url)
    hybrid = config.get("ENABLE_RAG_HYBRID_SEARCH") is True
    bypass = config.get("BYPASS_EMBEDDING_AND_RETRIEVAL") is True
    reranker_engine = config.get("RAG_RERANKING_ENGINE") or ""
    reranker_model = config.get("RAG_RERANKING_MODEL") or ""
    mark("embedding/retrieval not bypassed", not bypass, "BYPASS_EMBEDDING_AND_RETRIEVAL=" + str(bypass))
    mark("hybrid search enabled", hybrid, "ENABLE_RAG_HYBRID_SEARCH=" + str(hybrid))
    rerank_configured = bool(hybrid and reranker_engine and reranker_model)
    if os.environ.get("OWUI_RERANK_EXPECTED") == "1":
        mark("reranker active in Open WebUI configuration", rerank_configured,
             "engine=" + str(reranker_engine or "unset") + "; model=" + str(reranker_model or "unset"))
    elif rerank_configured:
        print("INFO  RAG config has reranker engine=" + str(reranker_engine) + "; model=" + str(reranker_model), flush=True)
    else:
        print("SKIP  reranker is optional and not configured", flush=True)

    # Build a minimal Office Open XML DOCX with Python stdlib; this drives the configured DOCX extraction path.
    document_xml = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p><w:r><w:t>" + content + "</w:t></w:r></w:p><w:sectPr/></w:body></w:document>")
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<?xml version=\"1.0\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/></Types>")
        archive.writestr("_rels/.rels", "<?xml version=\"1.0\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/></Relationships>")
        archive.writestr("word/document.xml", document_xml)
    boundary = "----owui" + uuid.uuid4().hex
    payload = (f"--{boundary}\r\n"
               f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
               "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n").encode() + docx.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    _, uploaded = request("/api/v1/files/?process=true&process_in_background=true", "POST", payload,
                          {"Content-Type": "multipart/form-data; boundary=" + boundary})
    file_id = uploaded.get("id") if isinstance(uploaded, dict) else None
    if not file_id: raise RuntimeError("upload returned no file id")
    mark("DOCX upload through Open WebUI API", True, "temporary file created")

    deadline = time.monotonic() + 300
    state = {}
    status = "pending"
    while time.monotonic() < deadline:
        _, state = request("/api/v1/files/" + urllib.parse.quote(file_id, safe="") + "/process/status")
        status = state.get("status", "unknown") if isinstance(state, dict) else "unknown"
        if status in ("completed", "failed"): break
        time.sleep(2)
    if status != "completed": raise RuntimeError("file processing status=" + status + "; " + str(state.get("error", "")))
    mark("Tika extraction + embeddings + Qdrant indexing", True, "processing completed")
    _, extracted = request("/api/v1/files/" + urllib.parse.quote(file_id, safe="") + "/data/content")
    extracted_text = extracted.get("content", "") if isinstance(extracted, dict) else ""
    mark("extracted DOCX text contains unique probe", marker in extracted_text)
    if marker not in extracted_text: raise RuntimeError("processed text lost the unique probe")

    query_body = json.dumps({"collection_name": "file-" + file_id,
                             "query": "Find the unique diagnostic code in the uploaded document: " + marker,
                             "k": 10, "k_reranker": 10, "hybrid": True}).encode()
    _, results = request("/api/v1/retrieval/query/doc", "POST", query_body,
                         {"Content-Type": "application/json"}, timeout=120)
    found = contains(results, marker)
    mark("hybrid/vector retrieval returned uploaded chunk", found,
         "Open WebUI query/doc follows active hybrid and reranker settings")
    if not found: raise RuntimeError("query did not return the uploaded probe chunk")
    if hybrid and rerank_configured:
        mark("retrieval with configured reranker", True, "query completed through active RAG settings")

    # Exercise the user-facing answer path too; model may be pinned via OPENWEBUI_E2E_MODEL.
    model = os.environ.get("OPENWEBUI_E2E_MODEL", "").strip()
    if not model:
        _, model_result = request("/api/models")
        model_list = model_result.get("data", model_result.get("models", [])) if isinstance(model_result, dict) else model_result
        model = next((item.get("id") for item in (model_list or []) if isinstance(item, dict) and item.get("id")), "")
    if not model:
        mark("chat completion using RAG context", False, "no model available; set OPENWEBUI_E2E_MODEL")
    else:
        chat_body = json.dumps({"model": model,
                                "messages": [{"role": "user", "content": "From the attached file, return the unique diagnostic code exactly. If unavailable, answer MISSING_CONTEXT."}],
                                "files": [{"type": "file", "id": file_id}],
                                "stream": False, "max_tokens": 100}).encode()
        _, answer = request("/api/chat/completions", "POST", chat_body,
                            {"Content-Type": "application/json"}, timeout=240)
        answer_text = ""
        if isinstance(answer, dict):
            choices = answer.get("choices") or []
            if choices:
                answer_text = (choices[0].get("message") or {}).get("content", "") or ""
        grounded = marker in answer_text
        mark("user-facing chat answer grounded in uploaded file", grounded, "model=" + model)
        if not grounded: raise RuntimeError("chat response did not include the unique code; inspect retrieved file context/model response")
except urllib.error.HTTPError as exc:
    try: detail = exc.read().decode("utf-8", "replace")[:500]
    except Exception: detail = ""
    print(f"FAIL  Open WebUI RAG E2E HTTP {exc.code}: {detail}; requires an admin API key and functioning RAG/chat APIs", flush=True)
    failed = True
except Exception as exc:
    print(f"FAIL  Open WebUI RAG E2E: {type(exc).__name__}: {exc}; inspect Open WebUI, Tika, embeddings, Qdrant, reranker, and model logs", flush=True)
    failed = True
finally:
    if file_id:
        try:
            code, result = request("/api/v1/files/" + urllib.parse.quote(file_id, safe=""), "DELETE")
            ok = code == 200
            mark("delete temporary file and per-file vectors", ok,
                 result.get("message", "HTTP " + str(code)) if isinstance(result, dict) else "HTTP " + str(code))
            if ok:
                try:
                    request("/api/v1/files/" + urllib.parse.quote(file_id, safe=""))
                    mark("verify file cleanup", False, "file still accessible")
                except urllib.error.HTTPError as exc:
                    mark("verify file cleanup", exc.code == 404, "HTTP " + str(exc.code))
        except Exception as exc:
            print(f"FAIL  cleanup temporary file {file_id}: {type(exc).__name__}: {exc}; remove it from Workspace > Files", flush=True)
            failed = True
sys.exit(1 if failed else 0)
PY
