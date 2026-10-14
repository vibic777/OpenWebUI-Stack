#!/usr/bin/env bash
# Non-destructive S3 CRUD probe through the Open WebUI container's network.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_ops-common.sh"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
check-seaweedfs.sh — проверить S3-доступ к SeaweedFS: создать, прочитать и удалить
временный тестовый объект. Остальные объекты и Knowledge-файлы не меняются.

Аргументы: не принимает параметры, кроме -h/--help.
Требования: запущенный Open WebUI/SeaweedFS; ключи и bucket читаются из .env.

Примеры:
  ./check-seaweedfs.sh
  cd /path/to/openwebui-stack && ./check-seaweedfs.sh
HELP
  exit 0
fi
(( $# == 0 )) || ops_die "аргументы не поддерживаются; используйте --help"
ENVF="$HERE/.env"
S3_ACCESS_KEY="$(ops_env_get "$ENVF" S3_ACCESS_KEY)"
S3_SECRET_KEY="$(ops_env_get "$ENVF" S3_SECRET_KEY)"
S3_BUCKET_NAME="$(ops_env_get "$ENVF" S3_BUCKET_NAME)"
S3_BUCKET_NAME="${S3_BUCKET_NAME:-openwebui}"
S3_ENDPOINT="http://openwebui-seaweedfs:8333"
[[ -n "$S3_ACCESS_KEY" && -n "$S3_SECRET_KEY" ]] \
  || ops_die "S3_ACCESS_KEY / S3_SECRET_KEY missing from $ENVF"
docker inspect -f '{{.State.Running}}' open-webui 2>/dev/null | grep -q true \
  || ops_die "open-webui is not running; start the Open WebUI Stack first"
export S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET_NAME S3_ENDPOINT
docker exec -i -e S3_ACCESS_KEY -e S3_SECRET_KEY -e S3_BUCKET_NAME -e S3_ENDPOINT open-webui python3 - <<'PY'
import datetime, hashlib, hmac, os, sys, urllib.error, urllib.parse, urllib.request, uuid

endpoint = os.environ["S3_ENDPOINT"].rstrip("/")
bucket = os.environ["S3_BUCKET_NAME"]
access_key = os.environ["S3_ACCESS_KEY"]
secret_key = os.environ["S3_SECRET_KEY"]
region = "us-east-1"
object_key = "_health-check/codex-" + uuid.uuid4().hex + ".txt"
payload = b"openwebui-stack-seaweedfs-s3-health-probe"
failed = False
created = False

def enc(value, safe="-_.~"):
    return urllib.parse.quote(value, safe=safe)

def request(method, key="", query=None, body=b""):
    query = query or {}
    path = "/" + enc(bucket)
    if key:
        path += "/" + enc(key, safe="/-_.~")
    query_string = "&".join(f"{enc(k)}={enc(v)}" for k, v in sorted(query.items()))
    parsed = urllib.parse.urlsplit(endpoint)
    host = parsed.netloc
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_headers = (f"host:{host}\n"
                         f"x-amz-content-sha256:{payload_hash}\n"
                         f"x-amz-date:{amz_date}\n")
    canonical = (f"{method}\n{path}\n{query_string}\n{canonical_headers}\n"
                 f"{signed_headers}\n{payload_hash}")
    scope = f"{date}/{region}/s3/aws4_request"
    string_to_sign = ("AWS4-HMAC-SHA256\n" + amz_date + "\n" + scope + "\n"
                      + hashlib.sha256(canonical.encode()).hexdigest())
    def sign(k, value):
        return hmac.new(k, value.encode(), hashlib.sha256).digest()
    signing_key = sign(sign(sign(sign(("AWS4" + secret_key).encode(), date), region), "s3"), "aws4_request")
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers = {
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                           f"SignedHeaders={signed_headers}, Signature={signature}"),
    }
    url = endpoint + path + ("?" + query_string if query_string else "")
    req = urllib.request.Request(url, data=body if method in ("PUT", "POST") else None,
                                 method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.status, response.read()

def mark(label, ok, detail=""):
    global failed
    print(("PASS  " if ok else "FAIL  ") + label + (" — " + detail if detail else ""), flush=True)
    failed |= not ok

try:
    status, _ = request("GET", query={"list-type": "2", "max-keys": "1"})
    mark("S3 ListBucket/authentication", status == 200, f"HTTP {status}")
    status, _ = request("PUT", object_key, body=payload)
    created = status in (200, 201)
    mark("upload temporary S3 object", created, f"HTTP {status}")
    if created:
        status, got = request("GET", object_key)
        mark("download and compare temporary object", status == 200 and got == payload,
             f"HTTP {status}; bytes={len(got)}")
except urllib.error.HTTPError as exc:
    detail = {403: "check S3_ACCESS_KEY/S3_SECRET_KEY against seaweedfs/s3.json",
              404: f"check that bucket '{bucket}' exists"}.get(exc.code, "inspect SeaweedFS logs and S3 endpoint")
    mark("S3 request", False, f"HTTP {exc.code}; {detail}")
except Exception as exc:
    mark("S3 request", False, f"{type(exc).__name__}: {exc}; check SeaweedFS health/network")
finally:
    if created:
        try:
            status, _ = request("DELETE", object_key)
            mark("delete temporary S3 object", status in (200, 204), f"HTTP {status}; cleanup")
        except Exception as exc:
            mark("delete temporary S3 object", False,
                 f"cleanup failed: {exc}; remove object key {object_key} from bucket {bucket}")

sys.exit(1 if failed else 0)
PY
