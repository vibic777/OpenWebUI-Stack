"""
title: Token counter (tokens + time)
author: openwebui-stack
version: 0.2.0
license: MIT
description: Under every assistant reply shows input/output tokens, total, seconds, tokens per second and the chat running total. Reads the usage that Open WebUI already collects from LM Studio; if the provider sent none, shows an estimate (marked with ~). Pure Python, works offline.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from pydantic import BaseModel, Field


def _num(v: Any) -> Optional[int]:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _usage_of(msg: dict) -> dict:
    """Extract known token usage fields from an Open WebUI message."""
    u = msg.get("usage")
    if not isinstance(u, dict) or not u:
        info = msg.get("info")
        u = (info or {}).get("usage") if isinstance(info, dict) else None
        if not isinstance(u, dict) and isinstance(info, dict) and info.get("prompt_eval_count") is not None:
            u = {"prompt_tokens": info.get("prompt_eval_count"), "completion_tokens": info.get("eval_count")}
    if not isinstance(u, dict):
        return {"in": None, "out": None, "total": None}
    i = _num(u.get("input_tokens")) if u.get("input_tokens") is not None else _num(u.get("prompt_tokens"))
    o = _num(u.get("output_tokens")) if u.get("output_tokens") is not None else _num(u.get("completion_tokens"))
    total = _num(u.get("total_tokens"))
    if total is None and i is not None and o is not None:
        total = i + o
    return {"in": i, "out": o, "total": total}


def _text(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return ""


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Filter order (lower runs first)")
        show_speed: bool = Field(default=True, description="Show tokens per second")
        show_chat_total: bool = Field(default=True, description="Show the running total of tokens used in this chat")
        estimate_if_missing: bool = Field(default=True, description="Estimate tokens from text length if provider usage is missing")
        chars_per_token: float = Field(default=3.0, description="Approximate characters per token")

    def __init__(self):
        self.valves = self.Valves()
        self._t0: dict[str, float] = {}

    @staticmethod
    def _key(body: dict, metadata: Optional[dict]) -> str:
        md = metadata or {}
        return f"{md.get('chat_id') or body.get('chat_id') or ''}:{md.get('message_id') or body.get('id') or ''}"

    def inlet(self, body: dict, __user__: Optional[dict] = None, __metadata__: Optional[dict] = None) -> dict:
        self._t0[self._key(body, __metadata__)] = time.monotonic()
        if len(self._t0) > 200:
            for key in sorted(self._t0, key=self._t0.get)[:100]:
                self._t0.pop(key, None)
        if body.get("stream"):
            opts = body.get("stream_options") or {}
            opts["include_usage"] = True
            body["stream_options"] = opts
        return body

    async def outlet(self, body: dict, __event_emitter__: Any = None, __user__: Optional[dict] = None, __metadata__: Optional[dict] = None) -> dict:
        msgs = [m for m in (body.get("messages") or []) if isinstance(m, dict)]
        mid = body.get("id") or (__metadata__ or {}).get("message_id")
        idx = next((i for i, m in enumerate(msgs) if mid and m.get("id") == mid), None)
        if idx is None:
            idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "assistant"), None)
        if idx is None or not __event_emitter__:
            return body
        last = msgs[idx]
        usage = _usage_of(last)
        approx = False
        if usage["in"] is None and usage["out"] is None and self.valves.estimate_if_missing:
            cpt = max(self.valves.chars_per_token, 0.5)
            usage = {"in": round(sum(len(_text(m)) for m in msgs[:idx]) / cpt), "out": round(len(_text(last)) / cpt), "total": None}
            usage["total"] = usage["in"] + usage["out"]
            approx = True
        elapsed = None
        t0 = self._t0.pop(self._key(body, __metadata__), None)
        if t0 is not None:
            elapsed = time.monotonic() - t0
        mark = "~" if approx else ""
        parts = []
        if usage["in"] is not None: parts.append(f"in {mark}{usage['in']}")
        if usage["out"] is not None: parts.append(f"out {mark}{usage['out']}")
        if usage["total"] is not None: parts.append(f"Σ {mark}{usage['total']}")
        if elapsed is not None:
            parts.append(f"{elapsed:.1f} s")
            if self.valves.show_speed and usage["out"] and elapsed > 0: parts.append(f"{mark}{usage['out'] / elapsed:.0f} tok/s")
        if self.valves.show_chat_total:
            chat_total = sum(v for v in (_usage_of(m)["total"] for m in msgs[:idx + 1] if m.get("role") == "assistant") if v)
            if chat_total and not approx: parts.append(f"chat Σ {chat_total}")
        description = "📊 " + (" · ".join(parts) if parts else "no usage data from the provider")
        await __event_emitter__({"type": "status", "data": {"description": description, "done": True}})
        return body
