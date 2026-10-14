#!/usr/bin/env python3
"""Install/list/remove only this standalone Open WebUI Action."""
from __future__ import annotations
import argparse, getpass, json, os, ssl, sys, urllib.error, urllib.request

FID = "export_images_menu"
NAME = "Экспорт изображений (IMG)"
DESCRIPTION = "Выбор формата изображения: SVG, PNG, JPG или WebP."
MINIMUM_VERSION = (0, 11, 3)

def version_tuple(value):
    value=str(value or "").strip().lstrip("v")
    match=__import__("re").match(r"^(\d+)\.(\d+)\.(\d+)", value)
    return tuple(map(int,match.groups())) if match else None

def main() -> int:
    p = argparse.ArgumentParser(description=f"Install or remove {FID}")
    p.add_argument("--version", action="version", version="%(prog)s 2026.09.26.8")
    p.add_argument("--url", default=os.environ.get("OWUI_URL", "http://127.0.0.1:8080"))
    p.add_argument("--email", default="")
    p.add_argument("--token", default=os.getenv("OWUI_TOKEN", ""))
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--remove", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--dir", default="")
    a = p.parse_args()
    opener = urllib.request.build_opener()
    def call(method, path, body=None):
        headers = {"Accept":"application/json", "Content-Type":"application/json"}
        if a.token: headers["Authorization"] = f"Bearer {a.token}"
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(a.url.rstrip("/")+path, data=data, headers=headers, method=method)
        try:
            with opener.open(req, timeout=45) as response:
                raw=response.read(); return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404: return None
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}") from exc
    try:
        if not a.token:
            if not a.email: raise RuntimeError("Admin e-mail is required (--email)")
            if a.password_stdin:
                password=sys.stdin.readline().rstrip("\r\n")
            else:
                password=getpass.getpass("Open WebUI admin password: ")
            if not password: raise RuntimeError("Admin password is empty")
            auth=call("POST", "/api/v1/auths/signin", {"email":a.email,"password":password}) or {}
            a.token=auth.get("token","")
            if not a.token: raise RuntimeError("Sign-in failed: no token returned")
        functions=call("GET", "/api/v1/functions/") or []
        if isinstance(functions, dict): functions=functions.get("items",[])
        current=next((item for item in functions if item.get("id")==FID),None)
        if a.list:
            for item in functions: print(f"{item.get('id')}\t{item.get('name')}\tactive={item.get('is_active')}\tglobal={item.get('is_global')}")
            return 0
        if a.remove:
            if current:
                call("DELETE", f"/api/v1/functions/id/{FID}/delete")
                print(f"Removed {FID}")
            else: print(f"Not installed: {FID}")
            return 0
        version_info=call("GET", "/api/version") or {}
        installed_version=version_tuple(version_info.get("version") if isinstance(version_info,dict) else version_info)
        if installed_version is None:
            raise RuntimeError("Could not detect Open WebUI version from /api/version; install requires Open WebUI >= 0.11.3")
        if installed_version < MINIMUM_VERSION:
            raise RuntimeError(f"Open WebUI {installed_version} is too old; this Action requires >= 0.11.3")
        if not a.dir: raise RuntimeError("Installer directory (--dir) is required")
        from pathlib import Path
        source=(Path(a.dir)/"export_action.py").read_text(encoding="utf-8")
        payload={"id":FID,"name":NAME,"content":source,"meta":{"description":DESCRIPTION,"manifest":{}},"is_active":True,"is_global":True}
        if current: call("POST",f"/api/v1/functions/id/{FID}/update",payload)
        else: call("POST","/api/v1/functions/create",payload)
        current=call("GET",f"/api/v1/functions/id/{FID}") or {}
        if not current.get("is_active"): call("POST",f"/api/v1/functions/id/{FID}/toggle")
        current=call("GET",f"/api/v1/functions/id/{FID}") or {}
        if not current.get("is_global"): call("POST",f"/api/v1/functions/id/{FID}/toggle/global")
        current=call("GET",f"/api/v1/functions/id/{FID}") or {}
        if not current.get("is_active") or not current.get("is_global"):
            raise RuntimeError("Function was saved, but Active/Global state did not verify")
        print(f"Installed {FID} (Active + Global)")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 1
if __name__ == "__main__": raise SystemExit(main())
