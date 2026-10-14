#!/usr/bin/env python3
"""Install/remove selected standalone export Actions with one admin login."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

FUNCTIONS = {
    "images": ("export_images_menu_v2", "Экспорт изображений V2 (IMG)", "SVG, PDF рисунка, EPS, DXF, PNG/JPG/BMP/GIF/WebP локально в браузере."),
    "documents": ("export_documents_menu_v2", "Экспорт документов V2 (DOC)", "DOCX/PPTX по одному файлу; PDF документа; XLSX, VSDX, Draw.io, BPMN, Markdown и TXT."),
    "code": ("export_code_menu_v2", "Экспорт кода V2 (CODE)", "Исходники, включая PlantUML и Graphviz DOT."),
    "data": ("export_data_menu_v2", "Экспорт данных V2 (DATA)", "Экспорт всех блоков выбранного формата."),
}
MINIMUM_VERSION = (0, 11, 3)


def version_tuple(value: object) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value or "").lstrip("v"))
    return tuple(map(int, match.groups())) if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="version", version="%(prog)s 2026.10.11.3")
    parser.add_argument("--url", default=os.environ.get("OWUI_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--email", required=True)
    parser.add_argument("--operation", choices=("install", "remove"), required=True)
    parser.add_argument("--groups", nargs="+", choices=FUNCTIONS, required=True)
    parser.add_argument("--dir", required=True)
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        print("ERROR: empty admin password", file=sys.stderr)
        return 1

    opener = urllib.request.build_opener()
    token = ""

    def call(method: str, path: str, body=None):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(args.url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            with opener.open(request, timeout=45) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}") from exc

    try:
        auth = call("POST", "/api/v1/auths/signin", {"email": args.email, "password": password}) or {}
        token = auth.get("token", "")
        if not token:
            raise RuntimeError("Admin sign-in failed: no token returned")
        functions = call("GET", "/api/v1/functions/") or []
        if isinstance(functions, dict):
            functions = functions.get("items", [])

        if args.operation == "install":
            info = call("GET", "/api/version") or {}
            version = version_tuple(info.get("version") if isinstance(info, dict) else info)
            if version is None or version < MINIMUM_VERSION:
                raise RuntimeError("Open WebUI version is unknown or below required 0.11.3")

        for group in args.groups:
            fid, name, description = FUNCTIONS[group]
            current = next((item for item in functions if item.get("id") == fid), None)
            if args.operation == "remove":
                if current:
                    call("DELETE", f"/api/v1/functions/id/{fid}/delete")
                    print(f"Removed {fid}")
                else:
                    print(f"Not installed: {fid}")
                continue

            path = f"{args.dir}/{group}/export_action.py"
            with open(path, encoding="utf-8") as source_file:
                content = source_file.read()
            payload = {
                "id": fid,
                "name": name,
                "content": content,
                "meta": {"description": description, "manifest": {}},
                "is_active": True,
                "is_global": True,
            }
            if current:
                call("POST", f"/api/v1/functions/id/{fid}/update", payload)
            else:
                call("POST", "/api/v1/functions/create", payload)
            saved = call("GET", f"/api/v1/functions/id/{fid}") or {}
            if not saved.get("is_active"):
                call("POST", f"/api/v1/functions/id/{fid}/toggle")
            saved = call("GET", f"/api/v1/functions/id/{fid}") or {}
            if not saved.get("is_global"):
                call("POST", f"/api/v1/functions/id/{fid}/toggle/global")
            saved = call("GET", f"/api/v1/functions/id/{fid}") or {}
            if not saved.get("is_active") or not saved.get("is_global"):
                raise RuntimeError(f"Could not verify Active + Global state for {fid}")
            print(f"Installed {fid} (Active + Global)")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
