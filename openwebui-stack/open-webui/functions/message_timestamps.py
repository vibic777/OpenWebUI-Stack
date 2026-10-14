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


# The interface hides the time of each message with ".hover-reveal{opacity:0}" until the mouse is over it.
_REVEAL_JS = (
    "(function(){if(document.getElementById('owui-ts-css'))return;"
    "var s=document.createElement('style');s.id='owui-ts-css';"
    "s.textContent='time.hover-reveal{opacity:1!important;pointer-events:auto!important;}';"
    "document.head.appendChild(s);})();"
)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=10, description="Filter order (lower runs first)")
        utc_offset_hours: float = Field(default=3.0, description="Your time zone as a UTC offset (3 = Moscow, 0 = UTC, 8 = Beijing)")
        time_format: str = Field(default="%d.%m.%Y %H:%M:%S", description="strftime format of the stamp")
        prefix: str = Field(default="🕒", description="Symbol before the time (also used to recognise stamps)")
        show_native_timestamps: bool = Field(default=True, description="Keep the interface's own time labels of all messages always visible (not only on hover)")
        append_to_message: bool = Field(default=False, description="ALSO write a text stamp into the message itself (stored in the chat; copied/exported with it)")
        stamp_user_messages: bool = Field(default=True, description="Text stamps: also stamp the user's messages when Open WebUI passes them to the filter")
        stamp_assistant_messages: bool = Field(default=True, description="Text stamps: stamp the model's replies")

    def __init__(self) -> None:
        self.valves = self.Valves()

    # -- helpers -----------------------------------------------------------------
    def _re(self) -> re.Pattern:
        return re.compile(r"\n\n\*" + re.escape(self.valves.prefix) + r" [^\n*]{4,40}\*[ \t]*$")

    def _stamp(self, ts: Any) -> Optional[str]:
        try:
            t = float(ts)
        except (TypeError, ValueError):
            return None
        if t > 1e12:  # milliseconds
            t /= 1000.0
        local = time.gmtime(t + self.valves.utc_offset_hours * 3600)
        return f"\n\n*{self.valves.prefix} {time.strftime(self.valves.time_format, local)}*"

    # -- filter hooks ------------------------------------------------------------
    async def inlet(self, body: dict, __user__: Optional[dict] = None, __event_emitter__: Any = None) -> dict:
        """Before the request goes to the model: remove text stamps from the history; reveal native timestamps."""
        if self.valves.show_native_timestamps and __event_emitter__:
            await __event_emitter__({"type": "execute", "data": {"code": _REVEAL_JS}})
        pat = self._re()
        for m in body.get("messages") or []:
            c = m.get("content") if isinstance(m, dict) else None
            if isinstance(c, str):
                m["content"] = pat.sub("", c)
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        part["text"] = pat.sub("", part["text"])
        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None, **_: Any) -> dict:
        """After the reply is complete: optionally append a text stamp to every message that has none."""
        if not self.valves.append_to_message:
            return body
        pat = self._re()
        for m in body.get("messages") or []:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role == "user" and not self.valves.stamp_user_messages:
                continue
            if role == "assistant" and not self.valves.stamp_assistant_messages:
                continue
            if role not in ("user", "assistant"):
                continue
            c = m.get("content")
            if not isinstance(c, str) or not c.strip() or pat.search(c):
                continue
            stamp = self._stamp(m.get("timestamp"))
            if stamp:
                m["content"] = c.rstrip() + stamp
        return body
