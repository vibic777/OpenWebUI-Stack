#!/usr/bin/env python3
"""Install/remove only the export_entire_chat Open WebUI Function."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

FUNCTION_ID = "export_entire_chat"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install/remove export_entire_chat only")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.2")
    parser.add_argument("--url", default=os.environ.get("OWUI_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--email", default="")
    parser.add_argument("--token", default=os.getenv("OWUI_TOKEN", ""))
    parser.add_argument("--remove", nargs="?", const=FUNCTION_ID)
    parser.add_argument("--dir", default="")
    args = parser.parse_args()
    token = args.token

    def call(method: str, path: str, body=None):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(args.url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:400]}") from exc

    try:
        if not token:
            email = args.email or input("Open WebUI admin e-mail: ")
            password = os.getenv("OWUI_ADMIN_PASSWORD") or getpass.getpass("Open WebUI admin password: ")
            token = (call("POST", "/api/v1/auths/signin", {"email": email, "password": password}) or {}).get("token", "")
            if not token:
                raise RuntimeError("Sign-in response contained no token")

        functions = call("GET", "/api/v1/functions/") or []
        if isinstance(functions, dict):
            functions = functions.get("items", [])
        current = next((item for item in functions if item.get("id") == FUNCTION_ID), None)
        if args.remove:
            if args.remove != FUNCTION_ID:
                raise RuntimeError(f"Refusing to remove unexpected Function ID: {args.remove}")
            if current:
                call("DELETE", f"/api/v1/functions/id/{FUNCTION_ID}/delete")
                print(f"Removed {FUNCTION_ID}")
            else:
                print(f"Not installed: {FUNCTION_ID}")
            return 0

        root = Path(args.dir).resolve() if args.dir else Path(__file__).resolve().parent
        source = (root / "export_chat.py").read_text(encoding="utf-8")
        payload = {
            "id": FUNCTION_ID,
            "name": "Экспорт всего чата",
            "content": source,
            "meta": {"description": "Экспорт всей истории текущего чата в один DOCX, PPTX, XLSX, Markdown, TXT или JSON.", "manifest": {}},
            "is_active": True,
            "is_global": True,
        }
        if current:
            call("POST", f"/api/v1/functions/id/{FUNCTION_ID}/update", payload)
        else:
            call("POST", "/api/v1/functions/create", payload)
        saved = call("GET", f"/api/v1/functions/id/{FUNCTION_ID}") or {}
        if not saved.get("is_active"):
            call("POST", f"/api/v1/functions/id/{FUNCTION_ID}/toggle")
        saved = call("GET", f"/api/v1/functions/id/{FUNCTION_ID}") or {}
        if not saved.get("is_global"):
            call("POST", f"/api/v1/functions/id/{FUNCTION_ID}/toggle/global")
        saved = call("GET", f"/api/v1/functions/id/{FUNCTION_ID}") or {}
        if not saved.get("is_active") or not saved.get("is_global"):
            raise RuntimeError(f"Could not verify Active + Global state for {FUNCTION_ID}")
        print(f"Installed {FUNCTION_ID} (Active + Global)")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
