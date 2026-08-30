"""SSH transport for the MRV LX web configurator.

The LX firmware only initializes the first interactive process channel on an
SSH transport. Normal reads/writes therefore share one persistent transport
and one persistent process channel. Help probes use disposable connections
because the LX leaves partial commands in its line editor after '?'.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import asyncssh

log = logging.getLogger("lxconsole.ssh")

LEGACY_KEX = [
    "diffie-hellman-group-exchange-sha256",
    "diffie-hellman-group-exchange-sha1",
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group1-sha1",
]
LEGACY_ENC = [
    "aes128-ctr", "aes192-ctr", "aes256-ctr",
    "aes128-cbc", "aes192-cbc", "aes256-cbc", "3des-cbc",
]
LEGACY_MAC = ["hmac-sha2-256", "hmac-sha1", "hmac-sha1-96", "hmac-md5"]
LEGACY_HOSTKEY = ["ssh-rsa", "ssh-dss"]
ERROR_SIGNATURES = [
    "Syntax Error", "Invalid input", "Ambiguous command", "Unknown command",
    "Incomplete command", "Cannot Run setup from a remote location",
    "Permission denied", "Enter a digit",
]
_ERROR_RE = re.compile("|".join(re.escape(x) for x in ERROR_SIGNATURES), re.I)


@dataclass
class DeviceConfig:
    host: str
    port: int = 22
    username: str = "InReach"
    password: Optional[str] = "access"
    client_keys: list[str] = field(default_factory=list)
    prompt_re: str = r"[A-Za-z][\w .\-/]*:\d+\s*>+#?\s*$"
    pager_re: str = r"Type a key to continue, q to quit"
    enable: bool = False
    enable_command: str = "enable"
    enable_password: Optional[str] = "system"
    save_command: str = "save configuration flash"
    connect_timeout: int = 15
    command_timeout: int = 30
    legacy_algorithms: bool = True


class LXConnection:
    def __init__(self, cfg: DeviceConfig, emitter=None):
        self.cfg = cfg
        self._conn: Optional[asyncssh.SSHClientConnection] = None
        self._proc = None
        self._lock = asyncio.Lock()
        self._prompt = re.compile(cfg.prompt_re, re.MULTILINE)
        self._pager = re.compile(cfg.pager_re)
        self._emit = emitter or (lambda *a, **k: None)
        self._last_prompt = ""
        self._help_cache: dict[tuple[str, str], dict] = {}
        self._enabled = False

    def _connect_kwargs(self) -> dict:
        kw = {
            "host": self.cfg.host,
            "port": self.cfg.port,
            "username": self.cfg.username,
            "known_hosts": None,
            "connect_timeout": self.cfg.connect_timeout,
        }
        if self.cfg.password:
            kw["password"] = self.cfg.password
        if self.cfg.client_keys:
            kw["client_keys"] = self.cfg.client_keys
        if self.cfg.legacy_algorithms:
            kw.update(
                kex_algs=LEGACY_KEX,
                encryption_algs=LEGACY_ENC,
                mac_algs=LEGACY_MAC,
                server_host_key_algs=LEGACY_HOSTKEY,
            )
        return kw

    async def connect(self) -> None:
        async with self._lock:
            await self._connect_control()

    async def _connect_control(self) -> None:
        if self._conn is not None and self._proc is not None:
            return
        self._emit("status", state="connecting",
                   detail=f"{self.cfg.username}@{self.cfg.host}:{self.cfg.port}")
        self._conn = await asyncssh.connect(**self._connect_kwargs())
        self._proc = await self._conn.create_process(
            term_type="vt100", term_size=(160, 48)
        )
        greeting = await self._read_until_prompt(self._proc, self.cfg.connect_timeout)
        if not self._last_prompt:
            await self._close_control()
            raise RuntimeError("MRV CLI prompt was not received")
        self._emit("info", detail=f"persistent CLI ready: {self._last_prompt}")
        self._emit("status", state="idle", detail="connected")
        if self.cfg.enable:
            await self._enable(self._proc)

    async def _close_control(self) -> None:
        proc, conn = self._proc, self._conn
        self._proc = None
        self._conn = None
        self._enabled = False
        if proc is not None:
            try:
                proc.stdin.write_eof()
            except Exception:
                pass
        if conn is not None:
            conn.close()
            try:
                await asyncio.wait_for(conn.wait_closed(), timeout=3)
            except asyncio.TimeoutError:
                conn.abort()

    async def close(self) -> None:
        async with self._lock:
            await self._close_control()

    async def _ensure_control(self):
        if self._conn is None or self._proc is None:
            await self._connect_control()
        return self._proc

    async def _enable(self, proc) -> None:
        if self._enabled or self._last_prompt.endswith(">>"):
            self._enabled = True
            return
        self._emit("tx", data=self.cfg.enable_command)
        proc.stdin.write(self.cfg.enable_command + "\r")
        await asyncio.sleep(0.25)
        if self.cfg.enable_password:
            proc.stdin.write(self.cfg.enable_password + "\r")
        response = await self._read_until_prompt(proc, 8)
        if not self._last_prompt.endswith(">>"):
            raise RuntimeError("Superuser prompt was not received")
        self._enabled = True
        self._emit("info", detail="escalated to superuser")

    async def run(self, command: str) -> dict:
        async with self._lock:
            for attempt in range(2):
                try:
                    proc = await self._ensure_control()
                    return await self._one(proc, command)
                except (asyncssh.Error, OSError, EOFError, RuntimeError) as exc:
                    if attempt:
                        raise
                    self._emit("info", detail=f"control channel reconnect: {exc}")
                    await self._close_control()
        raise RuntimeError("command failed")

    async def _one(self, proc, command: str) -> dict:
        self._emit("tx", data=command)
        self._emit("status", state="busy", detail=command)
        proc.stdin.write(command + "\r")
        raw = await self._read_until_prompt(proc, self.cfg.command_timeout)
        cleaned = _clean(raw, command, self._prompt, self._pager)
        result = {"command": command, "output": cleaned}
        err = _find_error(cleaned)
        if err:
            result["error_detected"] = err
            self._emit("error", detail=f"device reported: {err}", command=command)
        self._emit("status", state="idle", detail="idle")
        return result

    async def run_config(self, commands: list[str], save: bool = False,
                         context: Optional[str] = None) -> dict:
        results: list[dict] = []
        saved = None
        async with self._lock:
            proc = await self._ensure_control()
            await self._enable(proc)
            if commands or context:
                results.append(await self._one(proc, "configuration"))
                if context:
                    results.append(await self._one(proc, context))
                for command in commands:
                    results.append(await self._one(proc, command))
                results.append(await self._one(proc, "end"))
            if save:
                result = await self._one(proc, self.cfg.save_command)
                results.append(result)
                saved = "error_detected" not in result
        errors = [r["error_detected"] for r in results if r.get("error_detected")]
        return {"results": results, "saved": saved, "errors": errors,
                "ok": not errors}

    async def cli_help(self, tokens: str = "", context: Optional[str] = None) -> dict:
        key = (_context_kind(context), tokens.strip())
        cached = self._help_cache.get(key)
        if cached is not None:
            self._emit("info", detail=f"help cache hit: {tokens or '?'}")
            return dict(cached)

        async with self._lock:
            conn = None
            try:
                self._emit("status", state="busy", detail=f"discovering: {tokens or '?'}")
                conn = await asyncssh.connect(**self._connect_kwargs())
                proc = await conn.create_process(term_type="vt100", term_size=(160, 48))
                await self._read_until_prompt(proc, self.cfg.connect_timeout)
                await self._enable(proc)
                if context:
                    await self._one(proc, "configuration")
                    await self._one(proc, context)
                probe = f"{tokens.strip()} ?" if tokens.strip() else "?"
                self._emit("tx", data=probe)
                proc.stdin.write(probe)
                help_text = await self._read_help(proc, self.cfg.command_timeout)
                result = {"tokens": tokens, "context": context,
                          "output": _clean(help_text, "", self._prompt, self._pager)}
                self._help_cache[key] = dict(result)
                self._emit("status", state="idle", detail="discovery complete")
                return result
            finally:
                if conn is not None:
                    conn.close()
                    try:
                        await asyncio.wait_for(conn.wait_closed(), timeout=3)
                    except asyncio.TimeoutError:
                        conn.abort()

    async def _read_help(self, proc, timeout: int) -> str:
        parts: list[str] = []
        try:
            async with asyncio.timeout(timeout):
                while True:
                    try:
                        chunk = await asyncio.wait_for(proc.stdout.read(4096), 0.65)
                    except asyncio.TimeoutError:
                        break
                    if not chunk:
                        break
                    parts.append(chunk)
                    self._emit("rx", data=chunk)
                    if self._pager.search("".join(parts)[-512:]):
                        proc.stdin.write(" ")
                        self._emit("info", detail="pager: sent space")
        except asyncio.TimeoutError:
            pass
        return "".join(parts)

    async def _read_until_prompt(self, proc, timeout: int) -> str:
        parts: list[str] = []
        tail = ""
        try:
            async with asyncio.timeout(timeout):
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        raise EOFError("SSH process channel closed")
                    parts.append(chunk)
                    self._emit("rx", data=chunk)
                    tail = (tail + chunk)[-1024:]
                    if self._pager.search(tail):
                        proc.stdin.write(" ")
                        self._emit("info", detail="pager: sent space")
                        tail = ""
                        continue
                    match = self._prompt.search(tail)
                    if match:
                        self._last_prompt = match.group(0).strip()
                        break
        except asyncio.TimeoutError as exc:
            self._emit("status", state="error", detail="command timed out")
            raise RuntimeError("command timed out waiting for MRV prompt") from exc
        return "".join(parts)

    async def device_info(self) -> dict:
        from .parsers import generic_keyvalue
        info = {"host": self.cfg.host, "ip": self.cfg.host,
                "port": str(self.cfg.port), "username": self.cfg.username}

        async def fields(command: str) -> dict:
            result = await self.run(command)
            return generic_keyvalue(result["output"]).get("fields", {})

        version = await fields("show version")
        for key, value in version.items():
            low = key.lower()
            if "software version (runtime)" in low:
                info["firmware"] = value
            elif "model" in low or "product" in low:
                info.setdefault("model", value)
        characteristics = await fields("show system characteristics")
        for key, value in characteristics.items():
            low = key.lower()
            if low in ("name", "system name", "server name"):
                info["name"] = value
            elif "model" in low or "type" in low:
                info.setdefault("model", value)
        # Valid on this LX firmware, retained for discovery/logging even though
        # the connection target remains the authoritative banner address.
        await fields("show system ip status")
        status = await fields("show system status")
        info["uptime"] = status.get("System Uptime", "")
        info["temp"] = status.get("Current OnBoard Temp", "")
        if self._last_prompt:
            info["hostname"] = self._last_prompt.split(":", 1)[0].strip()
        return info


def _context_kind(context: Optional[str]) -> str:
    if not context:
        return "root"
    return re.sub(r"\b\d+\b", "<n>", context.strip().lower())


def _find_error(text: str) -> Optional[str]:
    match = _ERROR_RE.search(text or "")
    return match.group(0) if match else None


def _clean(text: str, command: str, prompt: re.Pattern, pager: re.Pattern) -> str:
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if command and lines and command.strip() in lines[0]:
        lines = lines[1:]
    lines = [line for line in lines
             if not prompt.search(line) and not pager.search(line)]
    return "\n".join(lines).strip("\n")
