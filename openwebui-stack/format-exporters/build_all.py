#!/usr/bin/env python3
"""Build four standalone Open WebUI export Actions and their offline packages."""
from __future__ import annotations

import base64
import ast
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
MINIMUM_OPEN_WEBUI = "0.11.3"

GROUPS = {
    "images": {
        "id": "export_images_menu", "name": "Экспорт изображений (IMG)", "button": "IMG", "icon": ("#7C3AED", "I"),
        "description": "Выбор формата изображения: SVG, PNG, JPG или WebP.",
        "choices": {"SVG": "svg", "PNG": "png", "JPG": "jpg", "WebP": "webp"},
        "source": "image-exporter/functions/export_images.py", "kind": "images",
        "readme": "# Экспорт изображений\n\nОтдельный Action с меню SVG, PNG, JPG и WebP. WebP создаётся в браузере из найденного изображения PNG/JPG (или внутреннего файла Open WebUI) с проверкой декодирования и результата. Нужен современный браузер с `createImageBitmap` и WebP canvas. Код не требует дополнительных Python-библиотек.\n\nУстановка: `sudo ./install-functions.sh` (или `--email ADMIN_EMAIL`). Удаление только этого Action: `sudo ./remove-functions.sh`.\n\nПромпт-тест для SVG: попросите вывести один fenced-блок `svg` с простым SVG без внешних ссылок, скриптов, `foreignObject` и обработчиков событий. PNG/JPG/WebP проверяйте на настоящем изображении, приложенном к ответу.\n",
    },
    "documents": {
        "id": "export_documents_menu", "name": "Экспорт документов (DOC)", "button": "DOC", "icon": ("#2563EB", "D"),
        "description": "Выбор формата документа: DOCX, XLSX, PPTX, VSDX, PDF, Markdown или TXT.",
        "choices": {"DOCX": "docx", "XLSX": "xlsx", "PPTX": "pptx", "VSDX": "vsdx", "PDF": "pdf", "Markdown": "md", "TXT": "txt"},
        "source": "open-webui/functions/export_office.py", "kind": "documents",
        "readme": "# Экспорт документов\n\nОтдельный Action с меню DOCX, XLSX, PPTX, VSDX, PDF, Markdown и TXT. Зависит только от библиотек, уже имеющихся в образе Open WebUI; контейнер и сеть не нужны для установки. XLSX ожидает Markdown-таблицу.\n\nУстановка: `sudo ./install-functions.sh` (или `--email ADMIN_EMAIL`). Удаление только этого Action: `sudo ./remove-functions.sh`.\n\nДля DOCX/PDF/PPTX/TXT/Markdown дайте структурированный ответ с заголовками, списком и абзацем; для XLSX добавьте Markdown-таблицу. Для VSDX используйте Mermaid `flowchart TD` или `flowchart LR` с простыми узлами и `-->`. После скачивания откройте `.vsdx` в Visio и проверьте раскладку.\n",
    },
    "code": {
        "id": "export_code_menu", "name": "Экспорт кода (CODE)", "button": "CODE", "icon": ("#059669", "C"),
        "description": "Текстовый экспорт программного и веб-кода; код не исполняется.",
        "choices": {"PowerShell (PS1)": "ps1", "Bash (SH)": "sh", "Python (PY)": "py", "VBA Office (BAS)": "vba", "JavaScript (JS)": "js", "TypeScript (TS)": "ts", "PHP": "php", "HTML": "html", "CSS": "css", "Java": "java", "C": "c", "C++": "cpp", "C#": "cs", "Go": "go", "Rust": "rs", "SQL": "sql"},
        "source": "admin-stack-exporter/functions/export_admin_stack.py", "kind": "code",
        "readme": "# Экспорт кода и веб-форматов\n\nОтдельный Action: PowerShell, Bash, Python, VBA (`.bas`), JavaScript, TypeScript, PHP, HTML, CSS, Java, C, C++, C#, Go, Rust и SQL. Скачивает один соответствующий fenced-блок как текстовый файл. Ничего не исполняет и не запускает.\n\nУстановка: `sudo ./install-functions.sh` (или `--email ADMIN_EMAIL`). Удаление только этого Action: `sudo ./remove-functions.sh`.\n\nВ ответе должен быть ровно один блок с подходящей меткой, например `powershell`, `bash`, `python`, `vba`, `typescript`, `csharp` или `sql`.\n",
    },
    "data": {
        "id": "export_data_menu", "name": "Экспорт данных (DATA)", "button": "DATA", "icon": ("#D97706", "D"),
        "description": "Экспорт одного блока данных/конфигурации с проверкой там, где она доступна.",
        "choices": {"JSON": "json", "JSON Lines (JSONL)": "jsonl", "XML": "xml", "YAML (YML)": "yml", "TOML": "toml", "INI": "ini", "CONF": "conf", "ENV": "env", "Properties": "properties", "CSV": "csv", "TSV": "tsv"},
        "source": "admin-stack-exporter/functions/export_admin_stack.py", "kind": "data",
        "readme": "# Экспорт данных и конфигураций\n\nОтдельный Action: JSON, JSONL, XML, YAML/YML, TOML, INI, CONF, ENV, `.properties`, CSV и TSV. Выбирается ровно один fenced-блок нужной метки. JSON/JSONL/XML/TOML/INI/ENV/Properties/CSV/TSV получают синтаксические проверки; YAML проверяется базово на структуру/ошибки отступов без установки PyYAML. CONF сохраняется как текст, так как у `.conf` нет единого формального синтаксиса.\n\nУстановка: `sudo ./install-functions.sh` (или `--email ADMIN_EMAIL`). Удаление только этого Action: `sudo ./remove-functions.sh`.\n",
    },
}

ACTION_TEMPLATE = r'''"""
title: @@NAME@@
author: openwebui-stack
version: 1.0.5
required_open_webui_version: 0.11.3
license: MIT
description: @@DESCRIPTION@@
"""
from __future__ import annotations

import base64
import configparser
import csv
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from typing import Any
from pydantic import BaseModel

SOURCE_B64 = "@@SOURCE_B64@@"
GROUP = "@@GROUP@@"
CHOICES = @@CHOICES@@
_SOURCE = None


def _source():
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = {"__name__": "owui_standalone_export_source"}
        exec(compile(base64.b64decode(SOURCE_B64), "embedded_exporter.py", "exec"), _SOURCE)
    return _SOURCE


def _messages(body: dict) -> list[dict]:
    return [m for m in body.get("messages", []) if isinstance(m, dict)]


def _clicked(body: dict) -> list[dict]:
    messages = _messages(body)
    mid = body.get("id")
    found = [m for m in messages if mid and m.get("id") == mid and m.get("role") == "assistant"]
    return found or [m for m in reversed(messages) if m.get("role") == "assistant"][:1]


def _notify(emitter, level: str, text: str):
    if emitter:
        return emitter({"type": "notification", "data": {"type": level, "content": text}})


async def _choose(event_call, emitter):
    if not event_call:
        await _notify(emitter, "error", "Диалог выбора недоступен: требуется обычный чат Open WebUI с активной вкладкой.")
        return None
    result = await event_call({"type": "input", "data": {
        "title": "Выберите формат",
        "message": "Выберите формат для ответа, под которым нажата кнопка.",
        "input": {"type": "select", "options": list(CHOICES)},
    }})
    if result is False or result is None or result == "":
        await _notify(emitter, "info", "Экспорт отменён.")
        return None
    if isinstance(result, dict):
        if result.get("error"):
            await _notify(emitter, "error", f"Диалог выбора не завершён: {result['error']}")
        else:
            await _notify(emitter, "error", "Не удалось получить выбранный формат.")
        return None
    fmt = CHOICES.get(str(result))
    if not fmt:
        await _notify(emitter, "error", f"Неизвестный формат: {result}")
        return None
    return fmt


def _text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("text"))
    return ""


def _code_block(module: dict, messages: list[dict], fmt: str) -> str:
    aliases = {
        "ps1": {"powershell", "pwsh", "ps1"}, "sh": {"bash", "sh", "shell"},
        "py": {"python", "python3", "py"}, "vba": {"vba", "visualbasic", "visual-basic", "vb", "vb6"},
        "js": {"javascript", "js", "ecmascript"}, "ts": {"typescript", "ts"}, "php": {"php"},
        "html": {"html", "htm"}, "css": {"css"}, "java": {"java"}, "c": {"c"},
        "cpp": {"cpp", "c++", "cplusplus"}, "cs": {"csharp", "c#", "cs"}, "go": {"go", "golang"},
        "rs": {"rust", "rs"}, "sql": {"sql"}, "json": {"json"}, "jsonl": {"jsonl", "ndjson"},
        "xml": {"xml"}, "yml": {"yaml", "yml"}, "toml": {"toml"}, "ini": {"ini"},
        "conf": {"conf", "config"}, "env": {"env", "dotenv"}, "properties": {"properties", "java-properties"},
        "csv": {"csv"}, "tsv": {"tsv"},
    }
    parser = module["parse_markdown"]
    matches = [b for m in messages for b in parser(_text(m)) if b.get("t") == "code" and b.get("lang", "").lower() in aliases[fmt]]
    if len(matches) != 1:
        raise ValueError(f"Для {fmt.upper()} нужен ровно один отдельный fenced-блок с меткой {fmt}; найдено: {len(matches)}.")
    text = matches[0].get("text", "").strip()
    if not text:
        raise ValueError("Блок пустой.")
    return text


def _validate_data(source: str, fmt: str) -> None:
    if fmt == "json":
        json.loads(source)
    elif fmt == "jsonl":
        lines = [line for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if not lines:
            raise ValueError("JSONL-блок пустой.")
        for n, line in enumerate(lines, 1):
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Некорректный JSONL в строке {n}: {exc.msg}.") from exc
    elif fmt == "xml":
        ET.fromstring(source)
    elif fmt == "toml":
        import tomllib
        tomllib.loads(source)
    elif fmt == "ini":
        parser = configparser.ConfigParser()
        parser.read_string(source)
    elif fmt in {"env", "properties"}:
        for n, line in enumerate(source.splitlines(), 1):
            value = line.strip()
            if not value or value.startswith(("#", "!")):
                continue
            if fmt == "env":
                if value.startswith("export "):
                    value = value[7:].lstrip()
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", value):
                    raise ValueError(f"Некорректная запись ENV в строке {n}: ожидается KEY=VALUE.")
            elif not re.match(r"^[^:=\s][^:=]*\s*[:=]", value):
                raise ValueError(f"Некорректная запись Properties в строке {n}: ожидается key=value или key:value.")
    elif fmt in {"csv", "tsv"}:
        rows = list(csv.reader(io.StringIO(source), delimiter="," if fmt == "csv" else "\t"))
        if not rows or not any(rows):
            raise ValueError(f"Блок {fmt.upper()} пустой.")
        widths = {len(row) for row in rows if row}
        if len(widths) > 1:
            raise ValueError(f"В строках {fmt.upper()} разное количество колонок.")
    elif fmt == "yml":
        try:
            import yaml
        except ImportError:
            if not source.strip():
                raise ValueError("YAML-блок пустой.")
            for n, line in enumerate(source.splitlines(), 1):
                if "\t" in line[:len(line) - len(line.lstrip())]:
                    raise ValueError(f"В YAML запрещены табы в отступе (строка {n}).")
        else:
            yaml.safe_load(source)


def _download_js(raw: bytes, filename: str, mime: str) -> str:
    b64 = base64.b64encode(raw).decode("ascii")
    return f"""(()=>{{const b=atob("{b64}");const u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([u],{{type:{json.dumps(mime)}}}));a.download={json.dumps(filename, ensure_ascii=False)};document.body.appendChild(a);a.click();setTimeout(()=>{{URL.revokeObjectURL(a.href);a.remove();}},1000);}})();"""


def _webp_js(data_b64: str | None, file_path: str | None, filename: str) -> str:
    b64 = json.dumps(data_b64 or "")
    path = json.dumps(file_path or "")
    name = json.dumps(filename, ensure_ascii=False)
    return f"""(async()=>{{try{{let src;if({path}){{const u=new URL({path},location.href);if(u.origin!==location.origin||!/^\\/api\\/v1\\/files\\/[A-Za-z0-9_-]+\\/content$/.test(u.pathname))throw Error("Разрешены только внутренние файлы Open WebUI");const r=await fetch(u.href,{{credentials:"same-origin"}});if(!r.ok)throw Error("HTTP "+r.status);src=await r.blob();if(src.size>20971520)throw Error("Изображение превышает 20 МБ");}}else{{const raw=atob({b64});const bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);src=new Blob([bytes]);}}const head=new Uint8Array(await src.slice(0,8).arrayBuffer());const png=head.length>=8&&head[0]===137&&head[1]===80&&head[2]===78&&head[3]===71&&head[4]===13&&head[5]===10&&head[6]===26&&head[7]===10;const jpg=head.length>=3&&head[0]===255&&head[1]===216&&head[2]===255;if(!png&&!jpg)throw Error("Источник должен быть корректным PNG или JPEG");src=new Blob([await src.arrayBuffer()],{{type:png?"image/png":"image/jpeg"}});const bitmap=await createImageBitmap(src);const canvas=document.createElement("canvas");canvas.width=bitmap.width;canvas.height=bitmap.height;const ctx=canvas.getContext("2d");if(!ctx)throw Error("Canvas недоступен");ctx.drawImage(bitmap,0,0);bitmap.close();const out=await new Promise(resolve=>canvas.toBlob(resolve,"image/webp",0.92));if(!out||out.type!=="image/webp")throw Error("Браузер не поддерживает экспорт WebP");const a=document.createElement("a");a.href=URL.createObjectURL(out);a.download={name};document.body.appendChild(a);a.click();setTimeout(()=>{{URL.revokeObjectURL(a.href);a.remove();}},1000);}}catch(e){{console.error("WebP export:",e);window.dispatchEvent(new CustomEvent("open-webui-toast",{{detail:{{type:"error",content:"WebP: "+e.message}}}}));}}}})();"""


class Action:
    actions = [{"id": "choose", "name": "@@BUTTON@@", "icon_url": "@@ICON_URL@@"}]

    class Valves(BaseModel):
        pass

    def __init__(self):
        self.valves = self.Valves()

    async def action(self, body: dict, __id__: str | None = None, __event_emitter__=None, __event_call__=None, **kwargs):
        if __id__ not in (None, "choose"):
            await _notify(__event_emitter__, "error", "Неизвестное действие.")
            return None
        fmt = await _choose(__event_call__, __event_emitter__)
        if fmt is None:
            return None
        messages = _clicked(body)
        if not messages:
            await _notify(__event_emitter__, "warning", "Не найден ответ модели для экспорта.")
            return None
        try:
            module = _source()
            if GROUP == "documents":
                await module["Action"]().action(body, __id__=fmt, __event_emitter__=__event_emitter__, __event_call__=__event_call__)
                return None
            if GROUP == "images":
                if fmt != "webp":
                    await module["Action"]().action(body, __id__=fmt, __event_emitter__=__event_emitter__, __event_call__=__event_call__)
                    return None
                message = messages[0]
                raw = None
                last_error = None
                for input_fmt in ("png", "jpg"):
                    try:
                        raw = module["_payload"](message, input_fmt)
                        break
                    except ValueError as exc:
                        last_error = exc
                if raw is None:
                    raise last_error or ValueError("Не найдено изображение для преобразования в WebP.")
                data_b64 = base64.b64encode(raw).decode("ascii") if isinstance(raw, bytes) else None
                file_path = raw if isinstance(raw, str) else None
                name = f"{module['_image_title'](message)}-{time.strftime('%Y%m%d-%H%M')}.webp"
                js = _webp_js(data_b64, file_path, name)
                await __event_emitter__({"type": "execute", "data": {"code": js}})
                await _notify(__event_emitter__, "success", f"Подготовлен WebP: {name}.")
                return None

            source = _code_block(module, messages, fmt)
            if GROUP == "code":
                ext = fmt
                mime = "text/plain; charset=utf-8"
                if fmt == "vba": ext = "bas"
                filename = f"{fmt}-{time.strftime('%Y%m%d-%H%M')}.{ext}"
                raw = (source + "\n").encode("utf-8")
            else:
                _validate_data(source, fmt)
                ext = {"yml": "yml"}.get(fmt, fmt)
                mime = {"json": "application/json", "xml": "application/xml", "yml": "application/yaml", "csv": "text/csv", "tsv": "text/tab-separated-values"}.get(fmt, "text/plain; charset=utf-8")
                filename = f"data-{time.strftime('%Y%m%d-%H%M')}.{ext}"
                raw = (source + "\n").encode("utf-8")
            js = _download_js(raw, filename, mime)
            await __event_emitter__({"type": "execute", "data": {"code": js}})
            await _notify(__event_emitter__, "success", f"Скачивается {filename} ({len(raw) // 1024} КБ).")
        except ValueError as exc:
            await _notify(__event_emitter__, "warning", str(exc))
        except ImportError as exc:
            await _notify(__event_emitter__, "error", f"В образе Open WebUI отсутствует библиотека {exc.name}.")
        except Exception as exc:
            await _notify(__event_emitter__, "error", f"Экспорт {fmt.upper()} не выполнен: {type(exc).__name__}: {exc}")
        return None
'''

INSTALLER = '''#!/usr/bin/env python3
"""Install/list/remove only this standalone Open WebUI Action."""
from __future__ import annotations
import argparse, getpass, json, os, ssl, sys, urllib.error, urllib.request

FID = "@@ID@@"
NAME = "@@NAME@@"
DESCRIPTION = "@@DESCRIPTION@@"
MINIMUM_VERSION = (0, 11, 3)

def version_tuple(value):
    value=str(value or "").strip().lstrip("v")
    match=__import__("re").match(r"^(\\d+)\\.(\\d+)\\.(\\d+)", value)
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
                password=sys.stdin.readline().rstrip("\\r\\n")
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
            for item in functions: print(f"{item.get('id')}\\t{item.get('name')}\\tactive={item.get('is_active')}\\tglobal={item.get('is_global')}")
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
'''

INSTALL_SH = r'''#!/usr/bin/env bash
SCRIPT_VERSION="2026.09.26.8"
for version_arg in "$@"; do
  case "$version_arg" in --version|-V) printf '%s %s\n' "$(basename "$0")" "$SCRIPT_VERSION"; exit 0;; esac
done
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FDIR="$HERE/functions"; CONT="open-webui"; EMAIL="${OWUI_ADMIN_EMAIL:-}"; URL="${OWUI_URL:-http://127.0.0.1:8080}"; API_URL="$URL"
while [[ $# -gt 0 ]]; do case "$1" in
  --email) EMAIL="$2"; shift 2;; --container) CONT="$2"; shift 2;; --url) URL="$2"; shift 2;;
  -h|--help) echo "Usage: $0 [--url URL] [--email ADMIN_EMAIL] [--container open-webui]"; exit 0;;
  *) echo "Unknown option: $1" >&2; exit 2;; esac; done
docker inspect -f '{{.State.Running}}' "$CONT" | grep -q true || { echo "ERROR: container $CONT is not running" >&2; exit 1; }
if [[ -z "$EMAIL" ]]; then [[ -r /dev/tty ]] || { echo "ERROR: no terminal; pass --email ADMIN_EMAIL" >&2; exit 1; }; read -r -p 'Open WebUI admin e-mail: ' EMAIL </dev/tty; fi
[[ -n "$EMAIL" ]] || { echo "ERROR: admin e-mail is empty" >&2; exit 1; }
[[ -r /dev/tty ]] || { echo "ERROR: no terminal to read password" >&2; exit 1; }
read -r -s -p "Password for $EMAIL: " PASS </dev/tty; echo >/dev/tty
[[ -n "$PASS" ]] || { echo "ERROR: password is empty" >&2; exit 1; }
case "${URL%/}" in http://127.0.0.1:8080|http://localhost:3000) API_URL="http://127.0.0.1:8080";; esac
echo "Installing @@ID@@ through container $CONT (API $API_URL)..."
TMPD="/tmp/owui-@@ID@@-$$"; trap 'docker exec "$CONT" rm -rf "$TMPD" >/dev/null 2>&1 || true' EXIT
docker exec "$CONT" mkdir -p "$TMPD"
docker cp "$FDIR/export_action.py" "$CONT:$TMPD/"
docker cp "$FDIR/install_functions.py" "$CONT:$TMPD/"
printf '%s\n' "$PASS" | docker exec -i "$CONT" python3 "$TMPD/install_functions.py" --url "$API_URL" --email "$EMAIL" --dir "$TMPD" --password-stdin
'''

REMOVE_SH = r'''#!/usr/bin/env bash
SCRIPT_VERSION="2026.09.26.8"
for version_arg in "$@"; do
  case "$version_arg" in --version|-V) printf '%s %s\n' "$(basename "$0")" "$SCRIPT_VERSION"; exit 0;; esac
done
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; CONT="open-webui"; EMAIL="${OWUI_ADMIN_EMAIL:-}"; URL="${OWUI_URL:-http://127.0.0.1:8080}"; API_URL="$URL"
while [[ $# -gt 0 ]]; do case "$1" in
  --email) EMAIL="$2"; shift 2;; --container) CONT="$2"; shift 2;; --url) URL="$2"; shift 2;;
  -h|--help) echo "Usage: $0 [--url URL] [--email ADMIN_EMAIL] [--container open-webui]"; exit 0;;
  *) echo "Unknown option: $1" >&2; exit 2;; esac; done
docker inspect -f '{{.State.Running}}' "$CONT" | grep -q true || { echo "ERROR: container $CONT is not running" >&2; exit 1; }
if [[ -z "$EMAIL" ]]; then [[ -r /dev/tty ]] || { echo "ERROR: no terminal; pass --email ADMIN_EMAIL" >&2; exit 1; }; read -r -p 'Open WebUI admin e-mail: ' EMAIL </dev/tty; fi
[[ -n "$EMAIL" ]] || { echo "ERROR: admin e-mail is empty" >&2; exit 1; }
[[ -r /dev/tty ]] || { echo "ERROR: no terminal to read password" >&2; exit 1; }
read -r -s -p "Password for $EMAIL: " PASS </dev/tty; echo >/dev/tty
[[ -n "$PASS" ]] || { echo "ERROR: password is empty" >&2; exit 1; }
case "${URL%/}" in http://127.0.0.1:8080|http://localhost:3000) API_URL="http://127.0.0.1:8080";; esac
echo "Removing @@ID@@ through container $CONT (API $API_URL)..."
TMPD="/tmp/owui-@@ID@@-$$"; trap 'docker exec "$CONT" rm -rf "$TMPD" >/dev/null 2>&1 || true' EXIT
docker exec "$CONT" mkdir -p "$TMPD"
docker cp "$HERE/functions/install_functions.py" "$CONT:$TMPD/"
printf '%s\n' "$PASS" | docker exec -i "$CONT" python3 "$TMPD/install_functions.py" --url "$API_URL" --email "$EMAIL" --dir "$TMPD" --password-stdin --remove
'''


def source_bytes(rel: str, group: str) -> bytes:
    path = PROJECT_ROOT / rel
    if path.is_file():
        return path.read_bytes()
    artifact = HERE / group / "functions" / "export_action.py"
    tree = ast.parse(artifact.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SOURCE_B64"
            for target in node.targets
        ):
            return base64.b64decode(ast.literal_eval(node.value))
    raise FileNotFoundError(path)


def build() -> None:
    for folder, spec in GROUPS.items():
        exporter = base64.b64encode(source_bytes(spec["source"], folder)).decode("ascii")
        source = ACTION_TEMPLATE
        replacements = {
            "@@NAME@@": spec["name"], "@@DESCRIPTION@@": spec["description"],
            "@@SOURCE_B64@@": exporter, "@@GROUP@@": spec["kind"],
            "@@CHOICES@@": repr(spec["choices"]), "@@BUTTON@@": spec["button"],
            "@@ICON_URL@@": "data:image/svg+xml;base64," + base64.b64encode(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="1" y="1" width="30" height="30" rx="8" fill="{spec["icon"][0]}"/><text x="16" y="21" text-anchor="middle" font-family="Arial,sans-serif" font-size="16" font-weight="700" fill="white">{spec["icon"][1]}</text></svg>'.encode()
            ).decode("ascii"),
        }
        for old, new in replacements.items(): source = source.replace(old, new)
        if re.search(r"@@[A-Z_]+@@", source): raise ValueError(f"Unresolved marker in {folder}")
        package = HERE / folder
        functions = package / "functions"
        functions.mkdir(parents=True, exist_ok=True)
        (functions / "export_action.py").write_text(source, encoding="utf-8", newline="\n")
        installer = INSTALLER.replace("@@ID@@", spec["id"]).replace("@@NAME@@", spec["name"]).replace("@@DESCRIPTION@@", spec["description"])
        (functions / "install_functions.py").write_text(installer, encoding="utf-8", newline="\n")
        record = [{"id": spec["id"], "name": spec["name"], "content": source,
                   "meta": {"description": spec["description"], "manifest": {}}, "is_active": True, "is_global": True}]
        (functions / "functions.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (package / "README.md").write_text(spec["readme"], encoding="utf-8", newline="\n")
        (package / "install-functions.sh").write_text(INSTALL_SH.replace("@@ID@@", spec["id"]), encoding="utf-8", newline="\n")
        (package / "remove-functions.sh").write_text(REMOVE_SH.replace("@@ID@@", spec["id"]), encoding="utf-8", newline="\n")
        size = (functions / "export_action.py").stat().st_size
        print(f"Built {folder}: {spec['id']} ({size:,} bytes)")


if __name__ == "__main__": build()
