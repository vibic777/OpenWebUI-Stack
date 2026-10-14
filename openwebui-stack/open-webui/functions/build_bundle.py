#!/usr/bin/env python3
"""build_bundle.py - build the portable plugin bundle from the *.py functions in this folder.

Creates (stdlib only):
  functions.json                 importable in Open WebUI: Admin -> Functions -> Import (array of functions)
  <out>/owui-plugins-<ver>.zip   functions + functions.json + install_functions.py + INSTALL.txt (copy anywhere, no repo needed)

  python build_bundle.py [--version 0.4.0] [--out ../../../release]
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP = {"install_functions.py", "build_bundle.py"}

INSTALL_TXT = """Open WebUI plugins - portable bundle / Переносимый комплект плагинов Open WebUI
==========================================================================

Files / Файлы
  export_office.py      Action: DOCX / XLSX / PPTX / VSDX / PDF / MD / TXT / CSV / SVG / PNG / JPG buttons (no admin-stack formats)
  token_and_time.py     Filter: tokens in/out, total, seconds, tok/s and chat total under every reply
  message_timestamps.py Filter: date/time of EVERY message always visible (not only on hover)
  functions.json       the same functions in Open WebUI's import format
  install_functions.py standalone installer (Python 3.8+, no pip, no internet)

Three ways to install / Три способа (любой)
  1) MANUAL - Admin Panel -> Functions -> "+" -> paste the file content -> Save -> switch Active and Global ON.
     ВРУЧНУЮ - Admin Panel -> Functions -> "+" -> вставить содержимое файла -> Save -> включить Active и Global.
  2) IMPORT - Admin Panel -> Functions -> "Import Functions" -> choose functions.json -> then switch Active and Global ON.
     ИМПОРТ  - Admin Panel -> Functions -> "Import" -> выбрать functions.json -> включить Active и Global.
  3) SCRIPT - from any computer that reaches Open WebUI (asks the admin password, hidden):
     СКРИПТ  - с любого компьютера, который видит Open WebUI (пароль админа спросит скрытно):
       python install_functions.py --url https://IP_ADDRESS --email admin@example.com --insecure
       (--insecure only for a self-signed certificate / только для самоподписанного сертификата)
       on the server itself / на самом сервере:  python3 install_functions.py --email admin@example.com  (default URL http://127.0.0.1:8080)

Then reload the browser page (F5). Update = repeat the same step with the new files.

REMOVE / УДАЛИТЬ
  Manual / вручную:  Admin -> Functions -> the function -> "..." -> Delete
  Script / скриптом: python install_functions.py --url ... --email ... --remove message_timestamps      (one / одну)
                     python install_functions.py --url ... --email ... --remove-bundled                  (all of this bundle / все из комплекта)
  Only the plugin records are removed; chats and users are untouched. / Удаляются только плагины; чаты и пользователи не затрагиваются.

Timestamps without a plugin / штампы без плагина:  Admin -> Settings -> Interface -> Custom CSS ->
  time.hover-reveal { opacity: 1 !important; pointer-events: auto !important; }
Check / Проверка:  python install_functions.py --url ... --email ... --list

More / Подробнее: docs/PLUGIN-EXPORT.md (prompts, limits). Offline: nothing is downloaded; the plugin only uses
libraries already inside the stock Open WebUI image.
"""


def frontmatter(src: str) -> dict:
    out = {}
    m = re.match(r'\s*"""\s*(.*?)"""', src, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="")
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    version = a.version
    if not version:
        for cand in (HERE / "../../../VERSION", HERE / "../../VERSION"):
            if cand.exists():
                version = cand.read_text().strip()
                break
    version = version or "dev"

    files = sorted(p for p in HERE.glob("*.py") if p.name not in SKIP)
    items = []
    for f in files:
        src = f.read_text(encoding="utf-8").replace("\r\n", "\n")
        fm = frontmatter(src)
        items.append({
            "id": f.stem,
            "name": fm.get("title", f.stem),
            "meta": {"description": fm.get("description", "")[:300], "manifest": {}},
            "content": src,
        })
    (HERE / "functions.json").write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"functions.json: {len(items)} functions")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / f"owui-plugins-{version}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files + [HERE / "install_functions.py"]:
            z.writestr(f"owui-plugins-{version}/{f.name}", f.read_text(encoding="utf-8").replace("\r\n", "\n"))
        z.write(HERE / "functions.json", f"owui-plugins-{version}/functions.json")
        z.writestr(f"owui-plugins-{version}/INSTALL.txt", INSTALL_TXT)
    print("bundle:", zpath, f"({zpath.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
