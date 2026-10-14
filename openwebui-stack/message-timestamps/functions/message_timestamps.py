"""
title: Message timestamps
author: openwebui-stack
version: 1.1.0
license: MIT
description: Makes the date/time of EVERY chat message (yours and the model's) permanently visible instead of only on mouse-hover, using the interface's own timestamps. Optionally also appends a text stamp to replies (stored in the chat, removed again before the text goes to the model). Works offline.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from pydantic import BaseModel, Field


_REVEAL_JS = (
    "(function(){if(document.getElementById('owui-ts-css'))return;"
    "var s=document.createElement('style');s.id='owui-ts-css';"
    "s.textContent='time.hover-reveal{opacity:1!important;pointer-events:auto!important;}';"
    "document.head.appendChild(s);})();"
)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=10, description="Filter order (lower runs first)")
        utc_offset_hours: float = Field(default=3.0, description="UTC offset: 3 = Moscow, 0 = UTC, 8 = Beijing")
        time_format: str = Field(default="%d.%m.%Y %H:%M:%S", description="strftime format of the stamp")
        prefix: str = Field(default="🕒", description="Symbol before text timestamps")
        show_native_timestamps: bool = Field(default=True, description="Keep the interface's native timestamps visible")
        append_to_message: bool = Field(default=False, description="Also save text timestamps in messages")
        stamp_user_messages: bool = Field(default=True, description="Stamp user messages when enabled")
        stamp_assistant_messages: bool = Field(default=True, description="Stamp assistant replies when enabled")

    def __init__(self) -> None:
        self.valves = self.Valves()

    def _re(self) -> re.Pattern:
        return re.compile(r"\n\n\*" + re.escape(self.valves.prefix) + r" [^\n*]{4,40}\*[ \t]*$")

    def _stamp(self, ts: Any) -> Optional[str]:
        try:
            value = float(ts)
        except (TypeError, ValueError):
            return None
        if value > 1e12:
            value /= 1000.0
        local = time.gmtime(value + self.valves.utc_offset_hours * 3600)
        return f"\n\n*{self.valves.prefix} {time.strftime(self.valves.time_format, local)}*"

    async def inlet(self, body: dict, __user__: Optional[dict] = None, __event_emitter__: Any = None) -> dict:
        if self.valves.show_native_timestamps and __event_emitter__:
            await __event_emitter__({"type": "execute", "data": {"code": _REVEAL_JS}})
        pattern = self._re()
        for message in body.get("messages") or []:
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                message["content"] = pattern.sub("", content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        part["text"] = pattern.sub("", part["text"])
        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None, **_: Any) -> dict:
        if not self.valves.append_to_message:
            return body
        pattern = self._re()
        for message in body.get("messages") or []:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "user" and not self.valves.stamp_user_messages:
                continue
            if role == "assistant" and not self.valves.stamp_assistant_messages:
                continue
            if role not in ("user", "assistant"):
                continue
            content = message.get("content")
            if not isinstance(content, str) or not content.strip() or pattern.search(content):
                continue
            stamp = self._stamp(message.get("timestamp"))
            if stamp:
                message["content"] = content.rstrip() + stamp
        return body
