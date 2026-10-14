#!/usr/bin/env bash
# wipe-rag.sh — wipe the vector DB (Qdrant) and/or the file store (SeaweedFS S3), authenticated with the keys from .env.
# No aws-cli, no internet: pure Python stdlib (runs inside the open-webui container, or host python3).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"

usage() {
  ops_print_bilingual_header \
    "wipe-rag.sh — wipe vectors (Qdrant) and/or files (SeaweedFS S3) using the keys from .env." \
    "wipe-rag.sh — очистить векторную базу (Qdrant) и/или файловое хранилище (SeaweedFS S3) по ключам из .env."
  cat <<'HELP'
Использование:
  ./wipe-rag.sh MODE [options]

MODE (one of / одно из):
  --list       show what is stored (collections, object count), delete nothing
  --vectors    delete ALL Qdrant collections          (key: QDRANT_API_KEY)
  --files      delete ALL objects in the S3 bucket    (keys: S3_ACCESS_KEY / S3_SECRET_KEY, S3_BUCKET_NAME)
  --all        --vectors + --files
  --volumes    HARD reset: remove the Qdrant and SeaweedFS docker volumes and recreate them
               (only these two volumes, found by container mounts; Postgres is never touched)

Options / Параметры:
  --bucket NAME     override S3_BUCKET_NAME
  --qdrant-key K    override QDRANT_API_KEY        (prefer env var; CLI args are visible in `ps`)
  --s3-key A --s3-secret S   override S3 keys      (same warning)
  -y, --yes         no confirmation (or CONFIRM=yes)
  --dry-run         print plan only
  -h, --help        эта справка

Keys are read from ./.env (empty values are fine if unset). Env vars QDRANT_API_KEY, S3_ACCESS_KEY, S3_SECRET_KEY win over .env.
This is IRREVERSIBLE: make ./backup-stack.sh --full first. After wiping: delete the phantom Knowledge in the
UI (Postgres still lists the files) and re-upload documents. See ADMIN.md.
For routine cleanup that preserves Knowledge, use ./cleanup-chat-files.sh (preview first); this script's
--vectors/--files/--all modes are global and do not distinguish chat uploads from Knowledge.

Examples / Примеры:
  ./wipe-rag.sh --list
  ./wipe-rag.sh --vectors --yes
  QDRANT_API_KEY=... ./wipe-rag.sh --vectors -y
HELP
}

TARGET="$(basename "$HERE")"; MODE=""; YES=0; DRY=0; BUCKET_O=""; QK_O=""; SA_O=""; SS_O=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --list|--vectors|--files|--all|--volumes) MODE="${1#--}"; shift ;;
    --bucket) BUCKET_O="$2"; shift 2 ;;
    --qdrant-key) QK_O="$2"; shift 2 ;;
    --s3-key) SA_O="$2"; shift 2 ;;
    --s3-secret) SS_O="$2"; shift 2 ;;
    -y|--yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) ops_die "unknown arg: $1 (try --help)" ;;
  esac
done
[[ -n "$MODE" ]] || { usage; ops_die "choose a MODE (--list | --vectors | --files | --all | --volumes)"; }
DIR="$HERE"; DC="$(ops_compose "$DIR")"; ENVF="$DIR/.env"; FILES="$(ops_files "$DIR")"
QDRANT_API_KEY="${QK_O:-${QDRANT_API_KEY:-$(ops_env_get "$ENVF" QDRANT_API_KEY)}}"
S3_ACCESS_KEY="${SA_O:-${S3_ACCESS_KEY:-$(ops_env_get "$ENVF" S3_ACCESS_KEY)}}"
S3_SECRET_KEY="${SS_O:-${S3_SECRET_KEY:-$(ops_env_get "$ENVF" S3_SECRET_KEY)}}"
S3_BUCKET_NAME="${BUCKET_O:-$(ops_env_get "$ENVF" S3_BUCKET_NAME)}"; S3_BUCKET_NAME="${S3_BUCKET_NAME:-openwebui}"
ops_info "wipe-rag target=$TARGET mode=$MODE bucket=$S3_BUCKET_NAME qdrant_key=$([[ -n $QDRANT_API_KEY ]] && echo set || echo none) s3_keys=$([[ -n $S3_ACCESS_KEY ]] && echo set || echo none)"

if [[ "$MODE" != "list" && $DRY -eq 0 && $YES -ne 1 && "${CONFIRM:-}" != "yes" ]]; then
  [[ -t 0 ]] || ops_die "confirmation required but stdin is not a terminal: re-run with --yes (or CONFIRM=yes)"
  read -r -p "IRREVERSIBLE: wipe '$MODE' on $TARGET. Type 'wipe' to continue: " a
  [[ "$a" == "wipe" ]] || ops_die "cancelled"
fi

# Python worker. Inside open-webui container the service names resolve; on host use loopback ports.
run_py() { # action
  local action="$1" cmd=() qurl surl
  if docker inspect -f '{{.State.Running}}' open-webui 2>/dev/null | grep -q true; then
    qurl="http://openwebui-qdrant:6333"; surl="http://openwebui-seaweedfs:8333"
    cmd=(docker exec -i -e ACTION="$action" -e QDRANT_URL="$qurl" -e QDRANT_API_KEY -e S3_ENDPOINT="$surl" -e S3_ACCESS_KEY -e S3_SECRET_KEY -e S3_BUCKET_NAME open-webui python3 -)
  else
    command -v python3 >/dev/null 2>&1 || ops_die "open-webui is not running and host python3 is missing"
    qurl="http://127.0.0.1:6333"; surl="http://127.0.0.1:8333"
    cmd=(env ACTION="$action" QDRANT_URL="$qurl" S3_ENDPOINT="$surl" python3 -)
  fi
  export QDRANT_API_KEY S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET_NAME
  "${cmd[@]}" <<'PY'
import os, sys, hashlib, hmac, datetime, urllib.request, urllib.parse, urllib.error, json
import xml.etree.ElementTree as ET
A = os.environ["ACTION"]
def _die(msg):
    print("ERROR: " + msg, file=sys.stderr); sys.exit(1)

# ---------------- Qdrant (api-key header) ----------------
QURL = os.environ["QDRANT_URL"].rstrip("/"); QKEY = os.environ.get("QDRANT_API_KEY", "")
def q(method, path):
    h = {"api-key": QKEY} if QKEY else {}
    req = urllib.request.Request(QURL + path, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r:
        b = r.read(); return json.loads(b) if b else {}
def collections():
    return [c["name"] for c in q("GET", "/collections")["result"]["collections"]]

# ---------------- S3 (AWS SigV4, path-style; unsigned if no keys) ----------------
EP = os.environ["S3_ENDPOINT"].rstrip("/"); AK = os.environ.get("S3_ACCESS_KEY", ""); SK = os.environ.get("S3_SECRET_KEY", "")
BUCKET = os.environ["S3_BUCKET_NAME"]; REGION = "us-east-1"
def _q(s, safe="-_.~"): return urllib.parse.quote(s, safe=safe)
def s3(method, key="", query=None):
    query = query or {}
    path = "/" + BUCKET + (("/" + _q(key, "/-_.~")) if key else "")
    cq = "&".join(f"{_q(k)}={_q(v)}" for k, v in sorted(query.items()))
    headers = {}
    if AK and SK:
        host = urllib.parse.urlparse(EP).netloc
        t = datetime.datetime.now(datetime.timezone.utc); amz = t.strftime("%Y%m%dT%H%M%SZ"); ds = t.strftime("%Y%m%d")
        ph = hashlib.sha256(b"").hexdigest()
        hs = {"host": host, "x-amz-content-sha256": ph, "x-amz-date": amz}
        sh = ";".join(sorted(hs)); ch = "".join(f"{k}:{hs[k]}\n" for k in sorted(hs))
        canon = "\n".join([method, path, cq, ch, sh, ph])
        scope = f"{ds}/{REGION}/s3/aws4_request"
        sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canon.encode()).hexdigest()])
        def h(k, m): return hmac.new(k, m.encode(), hashlib.sha256).digest()
        k = h(h(h(h(("AWS4" + SK).encode(), ds), REGION), "s3"), "aws4_request")
        sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
        headers = {"x-amz-date": amz, "x-amz-content-sha256": ph,
                   "Authorization": f"AWS4-HMAC-SHA256 Credential={AK}/{scope}, SignedHeaders={sh}, Signature={sig}"}
    req = urllib.request.Request(EP + path + ("?" + cq if cq else ""), method=method, headers=headers)
    return urllib.request.urlopen(req, timeout=120)
def s3_keys():
    keys, tok = [], None
    while True:
        qs = {"list-type": "2", "max-keys": "1000"}
        if tok: qs["continuation-token"] = tok
        try:
            root = ET.fromstring(s3("GET", "", qs).read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None      # bucket missing
            raise
        ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
        keys += [c.find(ns + "Key").text for c in root.findall(ns + "Contents")]
        if (root.findtext(ns + "IsTruncated") or "false").lower() != "true": return keys
        tok = root.findtext(ns + "NextContinuationToken")

def main():
    if A == "list":
        print("qdrant collections:", collections())
        k = s3_keys()
        print(f"s3 bucket '{BUCKET}':", "MISSING" if k is None else f"{len(k)} objects")
    elif A == "vectors":
        cols = collections(); print("collections:", cols)
        for c in cols:
            q("DELETE", "/collections/" + urllib.parse.quote(c, safe="")); print("deleted", c)
        print("vectors done:", len(cols), "collections; left:", collections())
    elif A == "files":
        ks = s3_keys()
        if ks is None:
            print("bucket missing: nothing to delete")
        else:
            for i, key in enumerate(ks, 1):
                s3("DELETE", key)
                if i % 200 == 0: print("deleted", i, "/", len(ks))
            print("files done:", len(ks), "objects deleted; left:", len(s3_keys() or []))
    elif A == "mkbucket":
        try:
            s3("PUT", ""); print("bucket created:", BUCKET)
        except urllib.error.HTTPError as e:
            print("mkbucket:", e.code)

try:
    main()
except urllib.error.HTTPError as e:
    what = {401: "wrong/missing key", 403: "wrong/missing key", 404: "not found"}.get(e.code, "request failed")
    _die(f"HTTP {e.code} from {e.url.split('?')[0]}: {what}. Check QDRANT_API_KEY / S3_ACCESS_KEY / S3_SECRET_KEY in .env")
except urllib.error.URLError as e:
    _die(f"cannot reach the service: {e.reason}")
PY
}

vol_reset() { # container dest label
  local c="$1" d="$2" v; v="$(ops_container_volume "$c" "$d")"
  [[ -n "$v" ]] || ops_die "cannot find volume of $c:$d (is the container created?)"
  ops_info "reset volume $v ($c)"
  docker stop "$c" >/dev/null; docker rm -f "$c" >/dev/null; docker volume rm "$v" >/dev/null
}

if [[ $DRY -eq 1 ]]; then echo "DRY-RUN: mode=$MODE (no changes made)"; exit 0; fi
case "$MODE" in
  list)    run_py list ;;
  vectors) run_py vectors ;;
  files)   run_py files ;;
  all)     run_py vectors; run_py files ;;
  volumes)
    vol_reset openwebui-qdrant /qdrant/storage
    vol_reset openwebui-seaweedfs /data
    ( cd "$DIR" && $DC $FILES --env-file .env up -d qdrant seaweedfs ); sleep 5
    run_py mkbucket ;;
esac
if [[ "$MODE" != list ]]; then ops_info "DONE. Next: delete phantom Knowledge in the UI, re-upload documents."; fi
