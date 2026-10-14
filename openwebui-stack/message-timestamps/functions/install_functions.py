#!/usr/bin/env python3
"""Standalone Open WebUI API installer. Python 3.8+, standard library only."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Install/remove only message_timestamps in Open WebUI")
    p.add_argument("--version", action="version", version="%(prog)s 2026.09.25.1")
    p.add_argument("--url", default=os.environ.get("OWUI_URL", "http://127.0.0.1:8080"))
    p.add_argument("--email", default="")
    p.add_argument("--token", default=os.getenv("OWUI_TOKEN", ""))
    p.add_argument("--insecure", action="store_true")
    p.add_argument("--remove", action="store_true", help="remove this function")
    p.add_argument("--list", action="store_true")
    a = p.parse_args()
    ctx = ssl.create_default_context()
    if a.insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    def call(method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if a.token:
            headers["Authorization"] = f"Bearer {a.token}"
        req = urllib.request.Request(a.url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            with opener.open(req, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}") from exc

    try:
        if not a.token:
            email = a.email or input("Open WebUI admin e-mail: ")
            password = os.getenv("OWUI_ADMIN_PASSWORD") or getpass.getpass("Open WebUI admin password: ")
            result = call("POST", "/api/v1/auths/signin", {"email": email, "password": password})
            a.token = result.get("token", "")
            if not a.token:
                raise RuntimeError("Sign-in response contained no token")
        functions = call("GET", "/api/v1/functions/") or []
        if isinstance(functions, dict):
            functions = functions.get("items", [])
        if a.list:
            for f in functions:
                print(f"{f.get('id')}\t{f.get('name')}\tactive={f.get('is_active')}\tglobal={f.get('is_global')}")
            return 0
        fid = "message_timestamps"
        if a.remove:
            if any(f.get("id") == fid for f in functions):
                call("DELETE", f"/api/v1/functions/id/{fid}/delete")
                print(f"Removed {fid}")
            else:
                print(f"Not installed: {fid}")
            return 0
        source = (Path(__file__).resolve().parent / "message_timestamps.py").read_text(encoding="utf-8")
        current = next((f for f in functions if f.get("id") == fid), None)
        payload = {"id": fid, "name": "Message timestamps", "content": source, "meta": {"description": "Show timestamps for every message", "manifest": {}}}
        if current:
            call("POST", f"/api/v1/functions/id/{fid}/update", payload)
        else:
            call("POST", "/api/v1/functions/create", payload)
        current = call("GET", f"/api/v1/functions/id/{fid}")
        if isinstance(current, dict) and not current.get("is_active"):
            call("POST", f"/api/v1/functions/id/{fid}/toggle")
        if isinstance(current, dict) and not current.get("is_global"):
            call("POST", f"/api/v1/functions/id/{fid}/toggle/global")
        print(f"Installed {fid} (Active + Global)")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
