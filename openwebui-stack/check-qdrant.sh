#!/usr/bin/env bash
# Non-destructive Qdrant CRUD probe through the Open WebUI container's network.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
check-qdrant.sh — проверить Qdrant: создать временную коллекцию, записать/прочитать
точку и удалить временную коллекцию. Постоянные коллекции и Knowledge не меняются.

Аргументы: не принимает параметры, кроме -h/--help.
Требования: запущенный Open WebUI и доступный Qdrant; API key берётся из .env.

Примеры:
  ./check-qdrant.sh
  cd /path/to/openwebui-stack && ./check-qdrant.sh
HELP
  exit 0
fi
(( $# == 0 )) || ops_die "аргументы не поддерживаются; используйте --help"
QDRANT_API_KEY="$(ops_env_get "$HERE/.env" QDRANT_API_KEY)"
export QDRANT_API_KEY
docker inspect -f '{{.State.Running}}' open-webui 2>/dev/null | grep -q true \
  || ops_die "open-webui is not running; start the Open WebUI Stack first"
docker exec -i -e QDRANT_API_KEY open-webui python3 - <<'PY'
import json, os, sys, urllib.error, urllib.request, uuid

base = "http://openwebui-qdrant:6333"
key = os.environ.get("QDRANT_API_KEY", "")
headers = {"api-key": key} if key else {}
name = "codex_health_" + uuid.uuid4().hex[:16]
failed = False
created = False

def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    h = dict(headers)
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=12) as response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}

def mark(label, ok, detail=""):
    global failed
    print(("PASS  " if ok else "FAIL  ") + label + (" — " + detail if detail else ""), flush=True)
    failed |= not ok

try:
    status, data = call("GET", "/collections")
    mark("Qdrant REST API via Open WebUI network", status == 200 and "result" in data)
    status, data = call("PUT", "/collections/" + name, {"vectors": {"size": 2, "distance": "Dot"}})
    created = status in (200, 201) and bool(data.get("result"))
    mark("create temporary collection", created, name if created else str(data))
    if created:
        status, data = call("PUT", "/collections/" + name + "/points?wait=true", {
            "points": [{"id": 1, "vector": [0.25, 0.75], "payload": {"probe": name}}]
        })
        upserted = status in (200, 201) and data.get("status") in ("ok", "completed")
        mark("upsert temporary vector", upserted, str(data.get("status", "unexpected response")))
        status, data = call("POST", "/collections/" + name + "/points/scroll", {
            "limit": 10, "with_payload": True, "with_vector": True
        })
        points = data.get("result", {}).get("points", [])
        readback = any(p.get("id") == 1 and p.get("payload", {}).get("probe") == name
                       and p.get("vector") == [0.25, 0.75] for p in points)
        mark("read back vector and payload", status == 200 and readback)
except Exception as exc:
    mark("Qdrant CRUD request", False, f"{type(exc).__name__}: {exc}; inspect Qdrant health/API key/network")
finally:
    if created:
        try:
            status, data = call("DELETE", "/collections/" + name)
            deleted = status == 200 and bool(data.get("result"))
            mark("delete temporary collection", deleted, "cleanup" if deleted else str(data))
        except Exception as exc:
            mark("delete temporary collection", False, f"cleanup failed: {exc}; remove {name} manually")

sys.exit(1 if failed else 0)
PY
