"""sessions.py — manage connections to MULTIPLE LX devices at once."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from .events import bus
from .ssh import DeviceConfig, LXConnection


@dataclass
class Session:
    token: str
    conn: LXConnection
    info: dict


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def connect(self, cfg: DeviceConfig) -> Session:
        token = secrets.token_hex(8)
        emitter = lambda et, **d: bus.emit(et, session=token, **d)  # noqa: E731
        conn = LXConnection(cfg, emitter=emitter)
        await conn.connect()
        info = await conn.device_info()
        sess = Session(token=token, conn=conn, info=info)
        self._sessions[token] = sess
        bus.emit("status", session=token, state="idle", detail="connected")
        return sess

    def get(self, token: str | None) -> Session | None:
        return self._sessions.get(token) if token else None

    async def disconnect(self, token: str | None) -> bool:
        sess = self._sessions.pop(token, None) if token else None
        if sess:
            bus.emit("status", session=token, state="", detail="disconnected")
            await sess.conn.close()
            return True
        return False

    def list(self) -> list[dict]:
        return [{"token": t, **s.info} for t, s in self._sessions.items()]


manager = SessionManager()
