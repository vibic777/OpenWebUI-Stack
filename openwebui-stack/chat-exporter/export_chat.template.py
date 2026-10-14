"""
title: Экспорт всего чата
author: openwebui-stack
version: 1.0.2
required_open_webui_version: 0.11.3
license: MIT
description: Экспортирует всю переданную историю чата в один DOCX, PPTX, XLSX, Markdown, TXT или JSON.
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

from pydantic import BaseModel, Field

HELPER_B64 = "@@HELPER_B64@@"
FORMATS = {
    "DOCX — весь чат одним документом": "docx",
    "PPTX — весь чат одной презентацией": "pptx",
    "XLSX — одна книга, таблицы по листам": "xlsx",
    "Markdown — вся история (.md)": "md",
    "Обычный текст — вся история (.txt)": "txt",
    "JSON — сообщения чата (.json)": "json",
}
ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="1" y="1" width="30" height="30" rx="8" fill="#475569"/><text x="16" y="22" text-anchor="middle" font-family="Arial,sans-serif" font-size="19" font-weight="700" fill="#fff">X</text></svg>'
ICON_URL = "data:image/svg+xml;base64," + base64.b64encode(ICON_SVG.encode("utf-8")).decode("ascii")


def _helper() -> dict:
    ns = {"__name__": "owui_chat_export_helper"}
    exec(compile(base64.b64decode(HELPER_B64), "export_documents.py", "exec"), ns)
    return ns


def _content(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", "")) for part in content
            if isinstance(part, dict) and part.get("text")
        )
    return ""


def _messages(body: dict) -> list[dict]:
    messages = body.get("messages") or []
    return [m for m in messages if isinstance(m, dict) and m.get("role") in {"user", "assistant"}]


def _history(messages: list[dict]) -> str:
    helper = _helper()
    sections = []
    for message in messages:
        text = helper["_clean"](_content(message))
        if not text:
            continue
        role = "Пользователь" if message.get("role") == "user" else "Ассистент"
        sections.append(f"## {role}\n\n{text}")
    return "\n\n---\n\n".join(sections)


def _title(body: dict) -> str:
    title = body.get("chat", {}).get("title") if isinstance(body.get("chat"), dict) else None
    title = title or body.get("title") or "Экспорт чата"
    title = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", str(title)).strip(" ._")
    return (title or "Экспорт чата")[:80]


def _js_download(raw: bytes, name: str, mime: str) -> str:
    encoded = base64.b64encode(raw).decode("ascii")
    return f'''(function(){{const b=atob("{encoded}");const u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([u],{{type:{json.dumps(mime)}}}));a.download={json.dumps(name, ensure_ascii=False)};document.body.appendChild(a);a.click();setTimeout(()=>{{URL.revokeObjectURL(a.href);a.remove();}},1500);}})();'''


class Action:
    class Valves(BaseModel):
        priority: int = Field(default=20, description="Порядок кнопки среди Actions; ставит экспорт чата после четырёх кнопок экспортёра V2.")

    def __init__(self):
        self.valves = self.Valves()
        self.actions = [{"id": "choose", "name": "Экспорт чата", "icon_url": ICON_URL}]

    async def _notify(self, emitter: Any, kind: str, text: str) -> None:
        if emitter:
            await emitter({"type": "notification", "data": {"type": kind, "content": text}})

    async def action(self, body: dict, __id__: str | None = None,
                     __event_emitter__=None, __event_call__=None, **kwargs):
        if __id__ not in (None, "choose"):
            await self._notify(__event_emitter__, "error", "Неизвестное действие экспорта чата.")
            return None
        if not __event_call__:
            await self._notify(__event_emitter__, "error", "Выбор формата доступен в обычном чате Open WebUI.")
            return None
        selected = await __event_call__({"type": "input", "data": {
            "title": "Экспорт всего чата",
            "message": "В один файл будет собрана вся история текущего чата.",
            "input": {"type": "select", "options": list(FORMATS)},
        }})
        if selected is False or selected is None or selected == "":
            return None
        if selected not in FORMATS:
            await self._notify(__event_emitter__, "error", "Неизвестный формат экспорта.")
            return None

        fmt = FORMATS[selected]
        messages = _messages(body)
        md = _history(messages)
        if not md.strip():
            await self._notify(__event_emitter__, "warning", "В истории чата нет текста для экспорта.")
            return None

        helper = _helper()
        blocks = helper["parse_markdown"](md)
        title = _title(body)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        name = f"{title}-{stamp}.{fmt}"
        try:
            if fmt == "docx":
                raw = helper["build_docx"](blocks, title)
                mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                code = _js_download(raw, name, mime)
            elif fmt == "pptx":
                raw = helper["build_pptx"](blocks, title)
                mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                code = _js_download(raw, name, mime)
            elif fmt == "xlsx":
                raw = helper["build_xlsx"](blocks, title)
                mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                code = _js_download(raw, name, mime)
            elif fmt == "md":
                raw = (md.rstrip() + "\n").encode("utf-8")
                code = _js_download(raw, name, "text/markdown; charset=utf-8")
            elif fmt == "txt":
                raw = helper["build_txt"](blocks)
                code = _js_download(raw, name, "text/plain; charset=utf-8")
            elif fmt == "json":
                raw = (json.dumps(messages, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                code = _js_download(raw, name, "application/json; charset=utf-8")
            else:
                raise ValueError(f"Неподдерживаемый формат экспорта: {fmt}")
        except ValueError as exc:
            await self._notify(__event_emitter__, "warning", str(exc))
            return None
        except ImportError as exc:
            await self._notify(__event_emitter__, "error", f"Для экспорта требуется библиотека {exc.name} в образе Open WebUI.")
            return None
        except Exception as exc:
            await self._notify(__event_emitter__, "error", f"Экспорт не выполнен: {type(exc).__name__}: {exc}")
            return None

        if __event_emitter__:
            await __event_emitter__({"type": "execute", "data": {"code": code}})
        elif __event_call__:
            await __event_call__({"type": "execute", "data": {"code": code}})
        await self._notify(__event_emitter__, "success", f"Подготовлен один файл: {name}")
        return None
