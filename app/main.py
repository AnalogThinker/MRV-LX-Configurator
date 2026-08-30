"""main.py — FastAPI backend for the modern MRV LX console (multi-device)."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib

import asyncssh
import yaml
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import parsers
from .events import bus
from .sessions import manager
from .ssh import DeviceConfig

HERE = pathlib.Path(__file__).parent
REGISTRY = yaml.safe_load((HERE / "commands.yaml").read_text())

DEFAULTS = {
    "host": os.getenv("LX_HOST", ""),
    "port": int(os.getenv("LX_PORT", "22")),
    "username": os.getenv("LX_USER", "InReach"),
    "password": os.getenv("LX_PASSWORD", "access"),
    "enable_password": os.getenv("LX_ENABLE_PASSWORD", "system"),
}

app = FastAPI(title="LX Console (modern)")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


def _token(request: Request) -> str | None:
    return (request.headers.get("X-Session-Token")
            or request.query_params.get("token"))


def _require(request: Request):
    sess = manager.get(_token(request))
    return sess.conn if sess else None


@app.on_event("shutdown")
async def _shutdown() -> None:
    for t in list(manager._sessions):        # noqa: SLF001
        await manager.disconnect(t)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/actions")
async def actions() -> JSONResponse:
    return JSONResponse({"actions": REGISTRY.get("actions", {}),
                         "mutations": REGISTRY.get("mutations", {}),
                         "defaults": DEFAULTS})


class ConnectBody(BaseModel):
    host: str
    port: int = 22
    username: str = "InReach"
    password: str = "access"
    enable_password: str = "system"
    enable: bool = False


@app.post("/api/connect")
async def connect(body: ConnectBody) -> JSONResponse:
    if not body.host.strip():
        return JSONResponse({"error": "host/IP is required"}, status_code=400)
    cfg = DeviceConfig(host=body.host.strip(), port=body.port,
                       username=body.username.strip() or "InReach",
                       password=body.password or None, enable=body.enable,
                       enable_password=body.enable_password or None)
    try:
        sess = await manager.connect(cfg)
    except (asyncssh.Error, OSError, asyncio.TimeoutError) as exc:
        return JSONResponse({"error": f"connection failed: {exc}"}, status_code=502)
    return JSONResponse({"token": sess.token, "info": sess.info})


@app.post("/api/disconnect")
async def disconnect(request: Request) -> JSONResponse:
    return JSONResponse({"ok": await manager.disconnect(_token(request))})


@app.get("/api/info")
async def info(request: Request) -> JSONResponse:
    sess = manager.get(_token(request))
    if not sess:
        return JSONResponse({"error": "no session"}, status_code=401)
    return JSONResponse({"token": sess.token, "info": sess.info})


class RunBody(BaseModel):
    command: str


@app.post("/api/run")
async def run_custom(request: Request, body: RunBody) -> JSONResponse:
    conn = _require(request)
    if not conn:
        return JSONResponse({"error": "not connected"}, status_code=401)
    return JSONResponse(await conn.run(body.command))


class ActionBody(BaseModel):
    params: dict[str, str] = {}


@app.post("/api/action/{name}")
async def run_action(request: Request, name: str, body: ActionBody) -> JSONResponse:
    conn = _require(request)
    if not conn:
        return JSONResponse({"error": "not connected"}, status_code=401)
    spec = REGISTRY.get("actions", {}).get(name) or \
           REGISTRY.get("mutations", {}).get(name)
    if not spec:
        return JSONResponse({"error": f"unknown action '{name}'"}, status_code=404)
    try:
        command = spec["command"].format(**body.params)
    except KeyError as missing:
        return JSONResponse({"error": f"missing parameter {missing}"}, status_code=400)
    result = await conn.run(command)
    result["action"] = name
    result["label"] = spec.get("label", name)
    if spec.get("parser"):
        parsed = parsers.parse(spec["parser"], result.get("output", ""))
        if parsed:
            result["parsed"] = parsed
    return JSONResponse(result)


class ConfigBody(BaseModel):
    commands: list[str]
    context: str | None = None
    save: bool = False


@app.post("/api/config")
async def apply_config(request: Request, body: ConfigBody) -> JSONResponse:
    conn = _require(request)
    if not conn:
        return JSONResponse({"error": "not connected"}, status_code=401)
    cmds = [c.strip() for c in body.commands if c.strip()]
    if not cmds and not body.save:
        return JSONResponse({"error": "no commands provided"}, status_code=400)
    result = await conn.run_config(cmds, save=body.save,
                                   context=(body.context or None))
    return JSONResponse(result)


@app.post("/api/save")
async def save_config(request: Request) -> JSONResponse:
    conn = _require(request)
    if not conn:
        return JSONResponse({"error": "not connected"}, status_code=401)
    return JSONResponse(await conn.run_config([], save=True))


class IntrospectBody(BaseModel):
    context: str | None = None
    tokens: str = ""


@app.post("/api/introspect")
async def introspect(request: Request, body: IntrospectBody) -> JSONResponse:
    conn = _require(request)
    if not conn:
        return JSONResponse({"error": "not connected"}, status_code=401)
    res = await conn.cli_help(body.tokens, context=(body.context or None))
    parsed = parsers.cli_help(res["output"])
    parsed.update({"context": body.context, "tokens": body.tokens,
                   "raw": res["output"]})
    return JSONResponse(parsed)


@app.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    token = _token(request)

    async def gen():
        q = await bus.subscribe()
        try:
            while True:
                evt = await q.get()
                if not token or evt.get("session") in (None, token):
                    yield f"data: {json.dumps(evt)}\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.websocket("/ws/terminal")
async def terminal(ws: WebSocket) -> None:
    await ws.accept()
    sess = manager.get(ws.query_params.get("token"))
    if not sess:
        await ws.send_text("\r\n[no active session — connect first]\r\n")
        await ws.close()
        return
    conn = None
    try:
        conn = await asyncssh.connect(**sess.conn._connect_kwargs())  # noqa: SLF001
        async with conn.create_process(term_type="xterm-256color") as proc:
            async def pump_out() -> None:
                while True:
                    data = await proc.stdout.read(1024)
                    if not data:
                        break
                    await ws.send_text(data)

            reader = asyncio.create_task(pump_out())
            try:
                while True:
                    msg = await ws.receive_text()
                    proc.stdin.write(msg)
            finally:
                reader.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_text(f"\r\n[connection error] {exc}\r\n")
        except Exception:
            pass
    finally:
        if conn is not None:
            conn.close()
