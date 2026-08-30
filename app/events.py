"""events.py — a tiny async pub/sub bus for live activity streaming (SSE)."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class EventBus:
    def __init__(self, history: int = 400) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._log: list[dict] = []
        self._history = history

    def emit(self, etype: str, **data: Any) -> None:
        evt = {"type": etype, "ts": time.time(), **data}
        self._log.append(evt)
        if len(self._log) > self._history:
            self._log = self._log[-self._history:]
        for q in list(self._subs):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        for evt in self._log[-120:]:
            q.put_nowait(evt)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)


bus = EventBus()
