#!/usr/bin/env python3
"""install_functions.py - install / update Open WebUI Functions (plugins) through the HTTP API.

Standalone: Python 3.8+ standard library only. Works from ANY machine that can reach Open WebUI
(the server itself, your laptop, Windows or Linux). No docker, no pip, no internet.

  python install_functions.py --url https://IP_ADDRESS --email admin@example.com --insecure
  python install_functions.py --email admin@example.com --dir ./functions  # defaults to http://127.0.0.1:8080
  python install_functions.py --url https://host --token "$OWUI_TOKEN" --list
  python install_functions.py --url https://host --email admin@example.com --remove message_timestamps
  python install_functions.py --url https://host --email admin@example.com --remove-bundled     # remove all our plugins

Password: prompted (hidden) or $OWUI_ADMIN_PASSWORD. Token (Settings -> Account -> API keys or JWT): $OWUI_TOKEN.
Never put the password on the command line (it is visible to other users in `ps`).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path


def build_opener(insecure: bool):
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


class Api:
    def __init__(self, base: str, insecure: bool):
        self.base = base.rstrip("/")
        self.opener = build_opener(insecure)
        self.token = ""

    def call(self, method: str, path: str, body=None):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw[:300]
        except urllib.error.URLError as e:
            sys.exit(f"ERROR: cannot reach {self.base}: {e.reason}  (wrong --url? self-signed HTTPS needs --insecure)")


def meta_of(src: str) -> tuple[str, str]:
    title = re.search(r"^title:\s*(.+)$", src, re.M)
    desc = re.search(r"^description:\s*(.+)$", src, re.M)
    return (title.group(1).strip() if title else ""), (desc.group(1).strip()[:300] if desc else "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Install / update Open WebUI Functions through the API (stdlib only).")
    ap.add_argument("--version", action="version", version="%(prog)s 2026.09.25.1")
    ap.add_argument("--url", default=os.environ.get("OWUI_URL", "http://127.0.0.1:8080"), help="Open WebUI base URL (default http://127.0.0.1:8080; override with --url or OWUI_URL)")
    ap.add_argument("--email", default=os.environ.get("OWUI_ADMIN_EMAIL", ""), help="admin e-mail (or $OWUI_ADMIN_EMAIL)")
    ap.add_argument("--token", default=os.environ.get("OWUI_TOKEN", ""), help="admin API token instead of e-mail/password (or $OWUI_TOKEN)")
    ap.add_argument("--dir", default="", help="folder with *.py functions (default: folder of this script)")
    ap.add_argument("--file", action="append", default=[], help="install only this file (repeatable)")
    ap.add_argument("--no-global", action="store_true", help="enable but do not make Global")
    ap.add_argument("--insecure", action="store_true", help="do not verify the TLS certificate (self-signed)")
    ap.add_argument("--list", action="store_true", help="only list installed functions")
    ap.add_argument("--remove", metavar="ID", action="append", default=[], help="delete the function with this id (repeatable), e.g. --remove export_office")
    ap.add_argument("--remove-bundled", action="store_true", help="delete every function that has a *.py file in the bundle folder (all our plugins)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be done, change nothing")
    a = ap.parse_args()
    api = Api(a.url, a.insecure)
    if a.token:
        api.token = a.token
    else:
        email = a.email or input("Open WebUI admin e-mail: ").strip()
        pw = os.environ.get("OWUI_ADMIN_PASSWORD") or getpass.getpass(f"Password for {email}: ")
        s, r = api.call("POST", "/api/v1/auths/signin", {"email": email, "password": pw})
        if s != 200 or not isinstance(r, dict) or "token" not in r:
            sys.exit(f"ERROR: login failed (HTTP {s}): wrong e-mail/password. The account must be an ADMIN.")
        api.token = r["token"]
        if r.get("role") != "admin":
            sys.exit(f"ERROR: {email} is not an admin (role={r.get('role')})")

    if a.list:
        s, fl = api.call("GET", "/api/v1/functions/")
        if s != 200:
            sys.exit(f"ERROR: cannot list functions (HTTP {s}); admin rights needed")
        for f in fl:
            print(f"{f['id']:28} {f.get('type', ''):8} active={f.get('is_active')} global={f.get('is_global')}  {f.get('name', '')}")
        print(f"({len(fl)} functions)")
        return 0
    if a.remove or a.remove_bundled:
        ids = list(a.remove)
        if a.remove_bundled:
            folder0 = Path(a.dir) if a.dir else Path(__file__).resolve().parent
            ids += [p.stem for p in sorted(folder0.glob("*.py")) if p.name not in ("install_functions.py", "build_bundle.py")]
        rc = 0
        for fid in dict.fromkeys(ids):
            if a.dry_run:
                print(f"DRY-RUN: would delete {fid}")
                continue
            s, r = api.call("DELETE", f"/api/v1/functions/id/{fid}/delete")
            if s == 200:
                print(f"{fid}: deleted")
            elif s == 404 or (isinstance(r, dict) and "not" in str(r.get("detail", "")).lower()):
                print(f"{fid}: not installed (nothing to delete)")
            else:
                print(f"{fid}: delete FAILED (HTTP {s}): {r}", file=sys.stderr)
                rc = 1
        if not a.dry_run:
            print("Done. Reload the browser page (F5).")
        return rc

    here = Path(__file__).resolve().parent
    folder = Path(a.dir) if a.dir else here
    files = [Path(f) for f in a.file] or sorted(p for p in folder.glob("*.py") if p.name not in ("install_functions.py", "build_bundle.py"))
    if not files:
        sys.exit(f"ERROR: no function files (*.py) in {folder}")

    rc = 0
    for f in files:
        if not f.is_file():
            print(f"{f}: missing", file=sys.stderr)
            rc = 1
            continue
        fid = f.stem
        src = f.read_text(encoding="utf-8")
        title, desc = meta_of(src)
        form = {"id": fid, "name": title or fid, "content": src, "meta": {"description": desc, "manifest": {}}}
        s, cur = api.call("GET", f"/api/v1/functions/id/{fid}")
        exists = s == 200
        if a.dry_run:
            print(f"DRY-RUN: {'update' if exists else 'create'} {fid} ({len(src)} bytes), then Active{'' if a.no_global else ' + Global'}")
            continue
        if exists:
            s, r = api.call("POST", f"/api/v1/functions/id/{fid}/update", form)
        else:
            s, r = api.call("POST", "/api/v1/functions/create", form)
        if s != 200:
            print(f"{fid}: {'update' if exists else 'create'} FAILED (HTTP {s}): {r}", file=sys.stderr)
            rc = 1
            continue
        s, cur = api.call("GET", f"/api/v1/functions/id/{fid}")
        if isinstance(cur, dict) and not cur.get("is_active"):
            api.call("POST", f"/api/v1/functions/id/{fid}/toggle")
        if not a.no_global and isinstance(cur, dict) and not cur.get("is_global"):
            api.call("POST", f"/api/v1/functions/id/{fid}/toggle/global")
        s, cur = api.call("GET", f"/api/v1/functions/id/{fid}")
        cur = cur if isinstance(cur, dict) else {}
        print(f"{fid}: {'updated' if exists else 'created'}  type={cur.get('type')} active={cur.get('is_active')} global={cur.get('is_global')}")
    if rc == 0 and not a.dry_run:
        print("Done. Reload the browser page (F5): buttons appear under assistant messages.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
