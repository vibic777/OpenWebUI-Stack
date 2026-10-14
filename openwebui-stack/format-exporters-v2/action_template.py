"""
title: __NAME_JSON__
author: openwebui-stack
version: 2.0.0
required_open_webui_version: 0.11.3
license: MIT
description: @@DESCRIPTION@@
"""
from __future__ import annotations

import base64
import binascii
import configparser
import csv
import hashlib
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

GROUP = @@GROUP@@
CHOICES = @@CHOICES@@
OFFICE_B64 = "@@OFFICE_B64@@"
IMAGES_B64 = "@@IMAGES_B64@@"
_OFFICE: dict | None = None
_IMAGES: dict | None = None


def _office() -> dict:
    global _OFFICE
    if _OFFICE is None:
        _OFFICE = {"__name__": "owui_v2_office_support"}
        exec(compile(base64.b64decode(OFFICE_B64), "export_office.py", "exec"), _OFFICE)
    return _OFFICE


def _images() -> dict:
    global _IMAGES
    if _IMAGES is None:
        _IMAGES = {"__name__": "owui_v2_image_support"}
        exec(compile(base64.b64decode(IMAGES_B64), "export_images.py", "exec"), _IMAGES)
    return _IMAGES


def _messages(body: dict) -> list[dict]:
    return [item for item in body.get("messages", []) if isinstance(item, dict)]


def _clicked(body: dict) -> list[dict]:
    messages = _messages(body)
    mid = body.get("id")
    selected = [m for m in messages if mid and m.get("id") == mid and m.get("role") == "assistant"]
    return selected or [m for m in reversed(messages) if m.get("role") == "assistant"][:1]


def _text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("text"))
    return ""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug(text: str) -> str:
    value = re.sub(r"[^\wЀ-ӿ一-鿿-]+", "_", text, flags=re.U).strip("_")
    return (value or "artifact")[:42]


def _notify(emitter, level: str, text: str):
    if emitter:
        return emitter({"type": "notification", "data": {"type": level, "content": text}})


async def _choose(event_call, emitter):
    if not event_call:
        await _notify(emitter, "error", "Список форматов доступен только в обычном чате Open WebUI.")
        return None
    result = await event_call({"type": "input", "data": {
        "title": "Формат экспорта",
        "message": "Экспортируются все артефакты выбранного формата из ответа, под которым нажата кнопка.",
        "input": {"type": "select", "options": list(CHOICES)},
    }})
    if result is False or result is None or result == "":
        await _notify(emitter, "info", "Экспорт отменён.")
        return None
    if not isinstance(result, str) or result not in CHOICES:
        await _notify(emitter, "error", f"Неизвестный формат: {result}")
        return None
    return CHOICES[result]


def _code_blocks(messages: list[dict], fmt: str) -> list[str]:
    aliases = {
        "ps1": {"powershell", "pwsh", "ps1"}, "sh": {"bash", "sh", "shell"},
        "py": {"python", "python3", "py"}, "vba": {"vba", "visualbasic", "visual-basic", "vb", "vb6"},
        "js": {"javascript", "js", "ecmascript"}, "ts": {"typescript", "ts"}, "php": {"php"},
        "html": {"html", "htm"}, "css": {"css"}, "java": {"java"}, "c": {"c"},
        "cpp": {"cpp", "c++", "cplusplus"}, "cs": {"csharp", "c#", "cs"},
        "go": {"go", "golang"}, "rs": {"rust", "rs"}, "sql": {"sql"},
        "pascal": {"pascal"}, "qbasic": {"qbasic"},
        "asm": {"asm", "assembly"}, "fortran": {"fortran", "f90", "f95"},
        "lisp": {"lisp", "commonlisp", "common-lisp"},
        "delphi": {"delphi", "objectpascal", "object-pascal"},
        "autoit": {"autoit", "au3"}, "bat": {"bat", "batch"}, "cmd": {"cmd"},
        "powerquery": {"m", "pq", "powerquery", "power-query", "power query"},
        "drawio": {"drawio", "diagrams.net"}, "bpmn": {"bpmn"},
        "puml": {"plantuml", "puml"}, "dot": {"dot", "graphviz"},
        "eps": {"eps", "postscript"}, "dxf": {"dxf"},
        "json": {"json"}, "jsonl": {"jsonl", "ndjson"}, "xml": {"xml"},
        "yml": {"yaml", "yml"}, "toml": {"toml"}, "ini": {"ini"},
        "conf": {"conf", "config"}, "env": {"env", "dotenv"},
        "properties": {"properties", "java-properties"}, "csv": {"csv"}, "tsv": {"tsv"},
    }
    if fmt == "svg":
        aliases["svg"] = {"svg"}
    parser = _office()["parse_markdown"]
    wanted = aliases.get(fmt, {fmt})
    found: list[str] = []
    for message in messages:
        for block in parser(_text(message)):
            if block.get("t") == "code" and str(block.get("lang", "")).lower() in wanted:
                body = str(block.get("text", "")).strip()
                if body:
                    found.append(body)
    return found


def _validate_data(source: str, fmt: str) -> None:
    if fmt == "json":
        json.loads(source)
    elif fmt == "jsonl":
        lines = [line for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if not lines:
            raise ValueError("Пустой JSONL-блок.")
        for line_no, line in enumerate(lines, 1):
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Некорректный JSONL, строка {line_no}: {exc.msg}.") from exc
    elif fmt == "xml":
        ET.fromstring(source)
    elif fmt == "toml":
        import tomllib
        tomllib.loads(source)
    elif fmt == "ini":
        parser = configparser.ConfigParser()
        parser.read_string(source)
    elif fmt in {"env", "properties"}:
        for line_no, line in enumerate(source.splitlines(), 1):
            text = line.strip()
            if not text or text.startswith(("#", "!")):
                continue
            if fmt == "env":
                if text.startswith("export "):
                    text = text[7:].lstrip()
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", text):
                    raise ValueError(f"Некорректная запись ENV, строка {line_no}: ожидалось KEY=VALUE.")
            elif not re.match(r"^[^:=\s][^:=]*\s*[:=]", text):
                raise ValueError(f"Некорректная запись Properties, строка {line_no}: ожидалось key=value.")
    elif fmt in {"csv", "tsv"}:
        rows = list(csv.reader(io.StringIO(source), delimiter="," if fmt == "csv" else "\t"))
        widths = {len(row) for row in rows if row}
        if not rows or not widths:
            raise ValueError(f"Пустой блок {fmt.upper()}.")
        if len(widths) > 1:
            raise ValueError(f"В строках {fmt.upper()} разное количество столбцов.")
    elif fmt == "yml":
        try:
            import yaml
        except ImportError:
            if not source.strip():
                raise ValueError("Пустой YAML-блок.")
            for line_no, line in enumerate(source.splitlines(), 1):
                if "\t" in line[:len(line) - len(line.lstrip())]:
                    raise ValueError(f"В YAML запрещён таб в отступе, строка {line_no}.")
        else:
            yaml.safe_load(source)


def _validate_drawio(source: str) -> bytes:
    """Validate an editable diagrams.net mxfile before offering it as a download."""
    raw = source.strip().encode("utf-8")
    if not raw:
        raise ValueError("Пустая схема Draw.io.")
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Файл Draw.io превышает лимит 2 МБ.")
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.I):
        raise ValueError("DTD и XML-сущности в Draw.io не поддерживаются.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"Некорректный XML Draw.io: {exc}.") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "mxfile":
        raise ValueError("Ожидался корневой элемент <mxfile> формата Draw.io.")
    if not any(child.tag.rsplit("}", 1)[-1].lower() == "diagram" for child in root):
        raise ValueError("В mxfile не найдена диаграмма.")
    return raw + (b"\n" if not raw.endswith(b"\n") else b"")


def _validate_bpmn(source: str) -> bytes:
    raw = source.strip().encode("utf-8")
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("BPMN XML пуст или превышает лимит 2 МБ.")
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.I):
        raise ValueError("DTD и XML-сущности в BPMN не поддерживаются.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"Некорректный BPMN XML: {exc}.") from exc
    local = lambda node: node.tag.rsplit("}", 1)[-1].lower()
    if local(root) != "definitions" or not any(local(node) == "process" for node in root.iter()):
        raise ValueError("Ожидался BPMN <definitions> с элементом <process>.")
    return raw + (b"\n" if not raw.endswith(b"\n") else b"")


def _validate_vector_source(source: str, fmt: str) -> bytes:
    raw = source.strip().encode("utf-8")
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError(f"{fmt.upper()} пуст или превышает лимит 2 МБ.")
    text = raw.decode("utf-8")
    if fmt == "eps":
        if not text.startswith("%!PS-Adobe") or "%%BoundingBox:" not in text or not text.rstrip().endswith("%%EOF"):
            raise ValueError("EPS должен начинаться с %!PS-Adobe, содержать %%BoundingBox и завершаться %%EOF.")
    elif not re.search(r"(?m)^0\s*\nSECTION\s*\n", text) or not re.search(r"(?m)^0\s*\nEOF\s*$", text):
        raise ValueError("DXF должен содержать секцию SECTION и завершаться парой 0 / EOF.")
    return raw + (b"\n" if not raw.endswith(b"\n") else b"")


def _data_mime(fmt: str) -> str:
    return {
        "json": "application/json", "xml": "application/xml", "yml": "application/yaml",
        "csv": "text/csv", "tsv": "text/tab-separated-values",
    }.get(fmt, "text/plain; charset=utf-8")


def _data_uri_items(messages: list[dict], fmt: str) -> list[dict]:
    image_module = _images()
    found: list[dict] = []
    seen: set[str] = set()
    if fmt == "svg":
        for source in _code_blocks(messages, "svg"):
            raw = image_module["_safe_svg"](source)
            key = hashlib.sha256(raw).hexdigest()
            if key not in seen:
                seen.add(key)
                found.append({"raw": raw, "ext": "svg", "mime": "image/svg+xml"})
        uri_pattern = image_module["SVG_DATA_URI"]
        markup_pattern = image_module["SVG_MARKUP"]
        for message in messages:
            for text in image_module["_walk_strings"](message):
                for match in uri_pattern.finditer(text):
                    try:
                        svg = base64.b64decode(re.sub(r"\s+", "", match.group(1)), validate=True).decode("utf-8")
                    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
                        raise ValueError("Повреждённый SVG data URI.") from exc
                    raw = image_module["_safe_svg"](svg)
                    key = hashlib.sha256(raw).hexdigest()
                    if key not in seen:
                        seen.add(key)
                        found.append({"raw": raw, "ext": "svg", "mime": "image/svg+xml"})
                for match in markup_pattern.finditer(text):
                    raw = image_module["_safe_svg"](match.group(0))
                    key = hashlib.sha256(raw).hexdigest()
                    if key not in seen:
                        seen.add(key)
                        found.append({"raw": raw, "ext": "svg", "mime": "image/svg+xml"})
                for match in image_module["INTERNAL_FILE_URL"].finditer(text):
                    url = match.group(0).rstrip(".,;!)]}")
                    key = "url:" + url
                    if key not in seen:
                        seen.add(key)
                        found.append({"url": url, "ext": "svg", "mime": "image/svg+xml"})
    elif fmt in {"png", "jpg", "webp", "bmp"}:
        # Raster export prefers actual source rasters, then falls back to SVG
        # artifacts in the same answer and rasterizes them in the browser.
        wanted = "png" if fmt in {"png", "webp"} else "jpg"
        for message in messages:
            for text in image_module["_walk_strings"](message):
                for match in image_module["DATA_URI"].finditer(text):
                    subtype, encoded = match.groups()
                    kind = "png" if subtype.lower() == "png" else "jpg"
                    try:
                        raw = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise ValueError(f"Повреждённые данные {kind.upper()}.") from exc
                    if kind == "png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ValueError("Встроенный файл не имеет сигнатуру PNG.")
                    if kind == "jpg" and not raw.startswith(b"\xff\xd8\xff"):
                        raise ValueError("Встроенный файл не имеет сигнатуру JPEG.")
                    key = hashlib.sha256(raw).hexdigest()
                    if key not in seen:
                        seen.add(key)
                        found.append({"raw": raw, "ext": kind, "mime": f"image/{'png' if kind == 'png' else 'jpeg'}"})
                for match in image_module["INTERNAL_FILE_URL"].finditer(text):
                    url = match.group(0).rstrip(".,;!)]}")
                    key = "url:" + url
                    if key not in seen:
                        seen.add(key)
                        found.append({"url": url, "ext": wanted, "mime": "application/octet-stream"})
        if not found:
            for item in _data_uri_items(messages, "svg"):
                key = hashlib.sha256(item["raw"]).hexdigest() if item.get("raw") else "url:" + item["url"]
                if key not in seen:
                    seen.add(key)
                    found.append({**item, "ext": "svg", "mime": item.get("mime", "image/svg+xml"), "convert_from_svg": bool(item.get("raw"))})
    return found


def _download_js(items: list[dict], fmt: str) -> str:
    if fmt == "gif":
        frames = items[0].get("frames", []) if items else []
        payload = []
        for frame in frames:
            raw = frame.get("raw", b"")
            payload.append({
                "mime": frame.get("mime", "image/svg+xml"),
                "data": base64.b64encode(raw).decode("ascii") if isinstance(raw, bytes) else "",
                "url": frame.get("url", ""),
            })
        return _gif_download_js(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), items[0]["name"])
    payload = []
    for item in items:
        raw = item.get("raw", b"")
        payload.append({
            "name": item["name"], "mime": item["mime"], "output_mime": item.get("output_mime", item["mime"]),
            "data": base64.b64encode(raw).decode("ascii") if isinstance(raw, bytes) else "",
            "url": item.get("url", ""),
            "convert_from_svg": bool(item.get("convert_from_svg")),
        })
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    raster = fmt in {"png", "jpg", "webp", "bmp"}
    return f'''(async()=>{{const files={encoded};const pause=ms=>new Promise(r=>setTimeout(r,ms));for(const f of files){{try{{let blob;if(f.url){{const u=new URL(f.url,location.href);if(u.origin!==location.origin||!/^\\/api\\/v1\\/files\\/[A-Za-z0-9_-]+\\/content$/.test(u.pathname))throw Error("Разрешены только внутренние файлы Open WebUI");const r=await fetch(u.href,{{credentials:"same-origin"}});if(!r.ok)throw Error("HTTP "+r.status);blob=await r.blob();}}else{{const b=atob(f.data);const a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);blob=new Blob([a],{{type:f.mime}});}}if(blob.size>20971520)throw Error("Файл больше 20 МБ");if({json.dumps(fmt)}==="svg"||f.convert_from_svg||blob.type==="image/svg+xml"){{if(blob.size>2097152)throw Error("SVG больше 2 МБ");const doc=new DOMParser().parseFromString(await blob.text(),"image/svg+xml");if(doc.querySelector("parsererror")||doc.documentElement.localName!=="svg"||doc.querySelector("script,foreignObject,iframe,object,embed"))throw Error("Некорректный или активный SVG");for(const el of doc.querySelectorAll("*"))for(const attr of el.attributes){{const v=attr.value.trim().toLowerCase();if(attr.name.toLowerCase().startsWith("on")||/javascript:|data:text\\/html|url\\(\\s*['\\\"]?\\s*(?:https?:|\\/\\/)/.test(v))throw Error("SVG содержит активные или внешние ресурсы");if(["href","src"].includes(attr.localName.toLowerCase())&&v&&!v.startsWith("#"))throw Error("SVG содержит внешнюю ссылку");}}blob=new Blob([new XMLSerializer().serializeToString(doc)],{{type:"image/svg+xml"}});}}if({str(raster).lower()}){{const sourceUrl=URL.createObjectURL(blob);const bitmap=await new Promise((resolve,reject)=>{{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(Error("Браузер не смог декодировать изображение"));image.src=sourceUrl;}});URL.revokeObjectURL(sourceUrl);const canvas=document.createElement("canvas");canvas.width=bitmap.naturalWidth||bitmap.width;canvas.height=bitmap.naturalHeight||bitmap.height;const ctx=canvas.getContext("2d");if(!ctx)throw Error("Canvas недоступен");ctx.drawImage(bitmap,0,0);const mime={json.dumps({'png':'image/png','jpg':'image/jpeg','webp':'image/webp','bmp':'image/bmp'}.get(fmt,''))};if(mime==="image/bmp"){{const w=canvas.width,h=canvas.height,stride=(w*3+3)&~3,size=54+stride*h,out=new Uint8Array(size),view=new DataView(out.buffer);view.setUint16(0,0x4d42,true);view.setUint32(2,size,true);view.setUint32(10,54,true);view.setUint32(14,40,true);view.setInt32(18,w,true);view.setInt32(22,h,true);view.setUint16(26,1,true);view.setUint16(28,24,true);view.setUint32(34,stride*h,true);const pixels=ctx.getImageData(0,0,w,h).data;for(let y=0;y<h;y++)for(let x=0;x<w;x++){{const src=((h-1-y)*w+x)*4,dst=54+y*stride+x*3,a=pixels[src+3]/255;out[dst]=Math.round(pixels[src+2]*a+255*(1-a));out[dst+1]=Math.round(pixels[src+1]*a+255*(1-a));out[dst+2]=Math.round(pixels[src]*a+255*(1-a));}}blob=new Blob([out],{{type:mime}});}}else{{blob=await new Promise(resolve=>canvas.toBlob(resolve,mime,0.92));if(!blob||blob.type!==mime)throw Error("Браузер не поддерживает преобразование в "+mime);}}}}const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=f.name;document.body.appendChild(a);a.click();setTimeout(()=>{{URL.revokeObjectURL(a.href);a.remove();}},1500);await pause(300);}}catch(e){{console.error("Artifact download:",f.name,e);window.dispatchEvent(new CustomEvent("open-webui-toast",{{detail:{{type:"error",content:f.name+": "+e.message}}}}));}}}}}})();'''


def _gif_download_js(encoded_frames: str, filename: str) -> str:
    template = r'''(async()=>{const files=__FILES_JSON__,filename=__NAME_JSON__;try{if(files.length<2)throw Error("Для GIF-анимации нужны минимум два кадра");if(files.length>30)throw Error("GIF ограничен 30 кадрами");const load=async f=>{let blob;if(f.url){const u=new URL(f.url,location.href);if(u.origin!==location.origin||!/^\/api\/v1\/files\/[A-Za-z0-9_-]+\/content$/.test(u.pathname))throw Error("Разрешены только внутренние файлы Open WebUI");const r=await fetch(u.href,{credentials:"same-origin"});if(!r.ok)throw Error("HTTP "+r.status);blob=await r.blob();}else{const b=atob(f.data),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);blob=new Blob([a],{type:f.mime});}if(blob.size>20971520)throw Error("Кадр больше 20 МБ");if(blob.type==="image/svg+xml"){if(blob.size>2097152)throw Error("SVG больше 2 МБ");const d=new DOMParser().parseFromString(await blob.text(),"image/svg+xml");if(d.querySelector("parsererror,script,foreignObject,iframe,object,embed"))throw Error("Некорректный или активный SVG");for(const e of d.querySelectorAll("*"))for(const a of e.attributes){const v=a.value.trim().toLowerCase();if(a.name.toLowerCase().startsWith("on")||/javascript:|data:text\/html|@import|url\(\s*["']?\s*(?:https?:|\/\/)/.test(v)||(["href","src"].includes(a.localName.toLowerCase())&&v&&!v.startsWith("#")))throw Error("SVG содержит активные или внешние ресурсы");}blob=new Blob([new XMLSerializer().serializeToString(d)],{type:"image/svg+xml"});}const url=URL.createObjectURL(blob);try{return await new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>reject(Error("Браузер не прочитал кадр"));i.src=url;});}finally{URL.revokeObjectURL(url);}};const images=[];for(const f of files)images.push(await load(f));let w=images[0].naturalWidth||images[0].width,h=images[0].naturalHeight||images[0].height,scale=Math.min(1,800/w,800/h);w=Math.max(1,Math.floor(w*scale));h=Math.max(1,Math.floor(h*scale));if(w*h*images.length>4000000)throw Error("Слишком много пикселей для одного GIF; уменьшите размер кадров или их количество");const chunks=[],push=(...b)=>chunks.push(...b),u16=n=>[n&255,(n>>8)&255];push(71,73,70,56,57,97,...u16(w),...u16(h),247,0,0);for(let i=0;i<256;i++){const r=(i>>5)&7,g=(i>>2)&7,b=i&3;push(Math.round(r*255/7),Math.round(g*255/7),Math.round(b*255/3));}push(33,255,11,78,69,84,83,67,65,80,69,50,46,48,3,1,0,0,0);for(const image of images){const c=document.createElement("canvas");c.width=w;c.height=h;const x=c.getContext("2d");x.fillStyle="#fff";x.fillRect(0,0,w,h);x.drawImage(image,0,0,w,h);const p=x.getImageData(0,0,w,h).data,idx=new Uint8Array(w*h);for(let i=0,j=0;i<p.length;i+=4,j++){const a=p[i+3]/255,r=p[i]*a+255*(1-a),g=p[i+1]*a+255*(1-a),b=p[i+2]*a+255*(1-a);idx[j]=(Math.round(r*7/255)<<5)|(Math.round(g*7/255)<<2)|Math.round(b*3/255);}push(33,249,4,4,...u16(12),0,0,44,...u16(0),...u16(0),...u16(w),...u16(h),0,8);let bits=0,nb=0,packed=[];const emit=code=>{bits|=code<<nb;nb+=9;while(nb>=8){packed.push(bits&255);bits>>>=8;nb-=8;}};for(const v of idx){emit(256);emit(v);}emit(257);if(nb)packed.push(bits&255);for(let i=0;i<packed.length;i+=255){const part=packed.slice(i,i+255);push(part.length,...part);}push(0);}push(59);const out=new Uint8Array(chunks),blob=new Blob([out],{type:"image/gif"}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=filename;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1500);window.dispatchEvent(new CustomEvent("open-webui-toast",{detail:{type:"success",content:"GIF-анимация: "+images.length+" кадров"}}));}catch(e){console.error("GIF export:",e);window.dispatchEvent(new CustomEvent("open-webui-toast",{detail:{type:"error",content:"GIF: "+e.message}}));}})();'''
    return template.replace("__FILES_JSON__", encoded_frames).replace("__NAME_JSON__", json.dumps(filename))


def _browser_files(items: list[dict], ext: str, mime: str, prefix: str) -> list[dict]:
    stamp = _stamp()
    result = []
    for index, item in enumerate(items, 1):
        result.append({**item, "name": f"{prefix}-{stamp}-{index:02d}.{ext}", "mime": item.get("mime", mime), "output_mime": mime})
    return result


def _table_blocks(messages: list[dict]) -> list[dict]:
    office = _office()
    return [block for message in messages for block in office["parse_markdown"](_text(message)) if block.get("t") == "table"]


def _message_text(messages: list[dict]) -> str:
    return "\n\n".join(_text(message).strip() for message in messages if _text(message).strip())


def _artifacts(messages: list[dict], fmt: str) -> list[dict]:
    stamp = _stamp()
    if GROUP == "code":
        fmt_key, ext = fmt.split(":", 1) if ":" in fmt else (fmt, fmt)
        blocks = _code_blocks(messages, fmt_key)
        if not blocks:
            return []
        items = []
        for index, source in enumerate(blocks, 1):
            raw = (source.rstrip() + "\n").encode("utf-8")
            ext = "bas" if fmt_key == "vba" else ext
            items.append({"name": f"{fmt_key}-{stamp}-{index:02d}.{ext}", "mime": "text/plain; charset=utf-8", "raw": raw})
        return items
    if GROUP == "data":
        blocks = _code_blocks(messages, fmt)
        if not blocks and fmt in {"csv", "tsv"}:
            delimiter = "," if fmt == "csv" else "\t"
            for table in _table_blocks(messages):
                stream = io.StringIO(newline="")
                csv.writer(stream, delimiter=delimiter, lineterminator="\n").writerows(table["rows"])
                blocks.append(stream.getvalue().rstrip("\n"))
        if not blocks:
            return []
        items = []
        ext = "yml" if fmt == "yml" else fmt
        for index, source in enumerate(blocks, 1):
            try:
                _validate_data(source, fmt)
            except Exception as exc:
                raise ValueError(f"Блок {index} ({fmt.upper()}): {exc}") from exc
            raw = (source.rstrip() + "\n").encode("utf-8")
            items.append({"name": f"{fmt}-{stamp}-{index:02d}.{ext}", "mime": _data_mime(fmt), "raw": raw})
        return items
    if GROUP == "images":
        if fmt == "gif":
            frames = []
            seen_frames = set()
            for frame in _data_uri_items(messages, "png") + _data_uri_items(messages, "svg"):
                key = hashlib.sha256(frame["raw"]).hexdigest() if frame.get("raw") else "url:" + frame["url"]
                if key not in seen_frames:
                    seen_frames.add(key)
                    frames.append(frame)
            if len(frames) < 2:
                raise ValueError("Для GIF-анимации нужно минимум два fenced-блока SVG или два изображения.")
            return [{"name": f"animation-{stamp}.gif", "mime": "image/gif", "frames": frames}]
        if fmt == "svg_pdf":
            images = _data_uri_items(messages, "svg")
            if not images:
                return []
            if any(not item.get("raw") for item in images):
                raise ValueError("Для PDF рисунка используйте SVG в fenced-блоке или SVG-разметку в тексте; SVG-файл по внутренней ссылке нельзя встроить в печать.")
            svg_pages = "".join(f"<section>{item['raw'].decode('utf-8')}</section>" for item in images if item.get("raw"))
            html = (
                "<!doctype html><html><head><meta charset='utf-8'><style>"
                "@page{size:A4 landscape;margin:8mm}html,body{margin:0;padding:0}"
                "section{height:190mm;display:flex;align-items:center;justify-content:center;"
                "page-break-after:always;break-after:page}section:last-child{page-break-after:auto;break-after:auto}"
                "svg{width:100%;height:100%;object-fit:contain}"
                "</style></head><body>" + svg_pages + "</body></html>"
            )
            return [{
                "name": f"vector-artwork-{stamp}.pdf", "mime": "application/pdf",
                "browser_code": _office()["_js_print_html"](html),
            }]
        if fmt in {"eps", "dxf"}:
            blocks = _code_blocks(messages, fmt)
            if not blocks:
                return []
            mime = "application/postscript" if fmt == "eps" else "application/dxf"
            items = []
            for index, source in enumerate(blocks, 1):
                try:
                    raw = _validate_vector_source(source, fmt)
                except ValueError as exc:
                    raise ValueError(f"Блок {fmt.upper()} {index}: {exc}") from exc
                items.append({"raw": raw, "mime": mime})
            return _browser_files(items, fmt, mime, fmt)
        if fmt == "webp":
            images = _data_uri_items(messages, "webp")
            unique = []
            seen = set()
            for item in images:
                key = hashlib.sha256(item["raw"]).hexdigest() if item.get("raw") else "url:" + item["url"]
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            images = unique
        else:
            images = _data_uri_items(messages, fmt)
        if not images:
            return []
        mime = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "bmp": "image/bmp"}[fmt]
        for item in images:
            item["convert_from_svg"] = bool(item.get("convert_from_svg"))
        return _browser_files(images, fmt, mime, fmt)
    if GROUP == "documents" and fmt == "drawio":
        blocks = _code_blocks(messages, "drawio")
        if not blocks:
            return []
        items = []
        for index, source in enumerate(blocks, 1):
            try:
                raw = _validate_drawio(source)
            except ValueError as exc:
                raise ValueError(f"Схема Draw.io {index}: {exc}") from exc
            items.append({
                "name": f"diagram-{stamp}-{index:02d}.drawio",
                "mime": "application/vnd.jgraph.mxfile",
                "raw": raw,
            })
        return items
    if GROUP == "documents" and fmt == "bpmn":
        blocks = _code_blocks(messages, "bpmn")
        if not blocks:
            return []
        items = []
        for index, source in enumerate(blocks, 1):
            try:
                raw = _validate_bpmn(source)
            except ValueError as exc:
                raise ValueError(f"BPMN-схема {index}: {exc}") from exc
            items.append({"name": f"process-{stamp}-{index:02d}.bpmn", "mime": "application/xml", "raw": raw})
        return items
    office = _office()
    blocks = [block for message in messages for block in office["parse_markdown"](_text(message))]
    if fmt in {"docx", "pptx", "pdf"}:
        title = office["_title_of"](blocks)
        name = f"{_slug(title)}-{stamp}.{fmt}"
        if fmt == "pdf":
            html = office["build_pdf_html"](blocks, title)
            return [{"name": name, "browser_code": office["_js_print_html"](html)}]
        builders = {"docx": "build_docx", "pptx": "build_pptx"}
        mimes = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        raw = office[builders[fmt]](blocks, title)
        return [{"name": name, "mime": mimes[fmt], "raw": raw}]
    if fmt == "xlsx_split":
        tables = [block for block in blocks if block.get("t") == "table"]
        return [
            {"name": f"table-{stamp}-{index:02d}.xlsx", "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "raw": office["build_xlsx"]([table], f"Таблица {index}")}
            for index, table in enumerate(tables, 1)
        ]
    if fmt == "xlsx_all":
        if not any(block.get("t") == "table" for block in blocks):
            return []
        return [{"name": f"tables-{stamp}.xlsx", "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "raw": office["build_xlsx"](blocks, "Таблицы") }]
    if fmt == "vsdx":
        diagrams = [block for block in blocks if block.get("t") == "code" and str(block.get("lang", "")).lower() == "mermaid"]
        return [
            {"name": f"diagram-{stamp}-{index:02d}.vsdx", "mime": "application/vnd.ms-visio.drawing", "raw": office["build_vsdx"]([diagram], f"Схема {index}")}
            for index, diagram in enumerate(diagrams, 1)
        ]
    if fmt in {"md", "txt"}:
        text = _message_text(messages)
        if not text:
            return []
        if fmt == "md":
            raw = (text.rstrip() + "\n").encode("utf-8")
        else:
            raw = office["build_txt"](blocks)
        return [{"name": f"answer-{stamp}.{fmt}", "mime": "text/plain; charset=utf-8", "raw": raw}]
    return []


class Action:
    actions = [{"id": "choose", "name": "@@BUTTON@@", "icon_url": "@@ICON_URL@@"}]

    class Valves(BaseModel):
        priority: int = Field(default=@@PRIORITY@@, description="Фиксированный порядок кнопки экспорта")

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
            await _notify(__event_emitter__, "warning", "В выбранном сообщении ассистента нет артефактов.")
            return None
        try:
            artifacts = _artifacts(messages, fmt)
            if not artifacts:
                await _notify(__event_emitter__, "warning", "Артефакты выбранного формата в этом ответе не найдены.")
                return None
            if artifacts[0].get("browser_code"):
                code = artifacts[0]["browser_code"]
            elif GROUP == "images":
                code = _download_js(artifacts, fmt)
            else:
                safe = []
                for item in artifacts:
                    raw = item["raw"]
                    safe.append({"name": item["name"], "mime": item["mime"], "data": base64.b64encode(raw).decode("ascii")})
                payload = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
                code = f'''(async()=>{{const files={payload};for(const f of files){{const b=atob(f.data);const u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([u],{{type:f.mime}}));a.download=f.name;document.body.appendChild(a);a.click();setTimeout(()=>{{URL.revokeObjectURL(a.href);a.remove();}},1500);await new Promise(r=>setTimeout(r,300));}}}})();'''
            if __event_emitter__:
                await __event_emitter__({"type": "execute", "data": {"code": code}})
            elif __event_call__:
                await __event_call__({"type": "execute", "data": {"code": code}})
            if artifacts[0].get("browser_code"):
                await _notify(__event_emitter__, "info", "Открыта печать браузера. В диалоге выберите «Сохранить как PDF».")
            elif GROUP == "images":
                await _notify(__event_emitter__, "info", f"В браузер передано изображений: {len(artifacts)}. Дождитесь завершения преобразования и скачивания; если появится запрос, разрешите множественные загрузки для Open WebUI.")
            else:
                await _notify(__event_emitter__, "success", f"Подготовлено файлов: {len(artifacts)}. Если браузер запросит разрешение на множественную загрузку, разрешите его для Open WebUI.")
        except ValueError as exc:
            await _notify(__event_emitter__, "warning", str(exc))
        except ImportError as exc:
            await _notify(__event_emitter__, "error", f"Для экспорта требуется доступная в образе библиотека {exc.name}.")
        except Exception as exc:
            await _notify(__event_emitter__, "error", f"Экспорт не выполнен: {type(exc).__name__}: {exc}")
        return None
