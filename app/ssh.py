"""
ssh.py — SSH transport layer for the MRV LX console replacement.

Replaces the old j2ssh.jar (SSHTools J2SSH). Provides:
  * persistent, reusable connection to an LX device
  * legacy host-key algorithm support (the LX only offers ssh-rsa/ssh-dss)
  * optional superuser escalation ("enable" -> password)
  * one-shot CLI commands (read until prompt, auto-paging the '--More--' pager)
  * hierarchical configuration writes (configuration -> context -> cmds -> end)
  * context-sensitive introspection ("<partial> ?") for the guided config UI
  * device-error detection (flags "Syntax Error" etc.)
  * a raw interactive PTY stream for the web terminal (xterm.js)

CONFIRMED on-device (MRV LX-4048T-101AC):
  * `ssh -vv` -> LX offers host-key algos ssh-rsa, ssh-dss ONLY.
  * Login  : InReach / access -> CLI prompt "InReach:0 >".
  * Enable : `enable` + password `system` -> superuser "InReach:0 >>".
  * Config : `set` alone launches the setup wizard (refused remotely); real
    config uses hierarchical modes: configuration -> "Config:0 >>" ->
    "port async 1" -> "Async1:0 >>" -> speed/name/... -> end.
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
    "aes128-cbc", "aes192-cbc", "aes256-cbc",
    "3des-cbc",
]
LEGACY_MAC = ["hmac-sha2-256", "hmac-sha1", "hmac-sha1-96", "hmac-md5"]
LEGACY_HOSTKEY = ["ssh-rsa", "ssh-dss"]

# Device error signatures. The LX prints these but still returns a normal
# prompt, so a command can "fail silently" unless we scan for them.
ERROR_SIGNATURES = [
    "Syntax Error",
    "Invalid input",
    "Ambiguous command",
    "Unknown command",
    "Incomplete command",
    "Cannot Run setup from a remote location",
    "Permission denied",
]
_ERROR_RE = re.compile("|".join(re.escape(s) for s in ERROR_SIGNATURES),
                       re.IGNORECASE)


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
        self._lock = asyncio.Lock()
        self._prompt = re.compile(cfg.prompt_re, re.MULTILINE)
        self._pager = re.compile(cfg.pager_re)
        self._emit = emitter or (lambda *a, **k: None)
        self._last_prompt = ""

    # -- connection lifecycle -----------------------------------------------

    def _connect_kwargs(self) -> dict:
        kw: dict = dict(host=self.cfg.host, port=self.cfg.port,
                        username=self.cfg.username, known_hosts=None,
                        connect_timeout=self.cfg.connect_timeout)
        if self.cfg.password:
            kw["password"] = self.cfg.password
        if self.cfg.client_keys:
            kw["client_keys"] = self.cfg.client_keys
        if self.cfg.legacy_algorithms:
            kw.update(kex_algs=LEGACY_KEX, encryption_algs=LEGACY_ENC,
                      mac_algs=LEGACY_MAC, server_host_key_algs=LEGACY_HOSTKEY)
        return kw

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._emit("status", state="connecting",
                   detail=f"{self.cfg.username}@{self.cfg.host}:{self.cfg.port}")
        try:
            self._conn = await asyncssh.connect(**self._connect_kwargs())
        except Exception as exc:
            self._emit("status", state="error", detail=str(exc))
            raise
        self._emit("status", state="connected")

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def _ensure(self) -> asyncssh.SSHClientConnection:
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        return self._conn

    # -- one-shot command ---------------------------------------------------

    async def run(self, command: str) -> dict:
        conn = await self._ensure()
        async with self._lock:
            try:
                async with conn.create_process(term_type="vt100") as proc:
                    await self._prepare(proc)
                    return await self._one(proc, command)
            except asyncssh.Error as exc:
                log.warning("run() failed, reconnecting once: %s", exc)
                await self.close()
                conn = await self._ensure()
                async with conn.create_process(term_type="vt100") as proc:
                    await self._prepare(proc)
                    return await self._one(proc, command)

    async def _prepare(self, proc, force_enable: bool = False) -> None:
        await self._read_until_idle(proc, quiet=0.6)
        if self.cfg.enable or force_enable:
            self._emit("tx", data=self.cfg.enable_command)
            proc.stdin.write(self.cfg.enable_command + "\n")
            await asyncio.sleep(0.4)
            if self.cfg.enable_password:
                proc.stdin.write(self.cfg.enable_password + "\n")
            await self._read_until_prompt(proc, timeout=8)
            self._emit("info", detail="escalated to superuser")

    async def _one(self, proc, command: str) -> dict:
        self._emit("tx", data=command)
        self._emit("status", state="busy", detail=command)
        proc.stdin.write(command + "\n")
        out = await self._read_until_prompt(proc, timeout=self.cfg.command_timeout)
        self._emit("status", state="idle")
        cleaned = _clean(out, command, self._prompt, self._pager)
        result = {"command": command, "output": cleaned}
        err = _find_error(cleaned)
        if err:
            result["error_detected"] = err
            self._emit("error", detail=f"device reported: {err}", command=command)
        return result

    # -- write / configuration ----------------------------------------------

    async def run_config(self, commands: list[str], save: bool = False,
                         context: Optional[str] = None) -> dict:
        conn = await self._ensure()
        results: list[dict] = []
        async with self._lock:
            async with conn.create_process(term_type="vt100") as proc:
                await self._prepare(proc, force_enable=True)
                if commands or context:
                    results.append(await self._one(proc, "configuration"))
                    if context:
                        results.append(await self._one(proc, context))
                    for cmd in commands:
                        results.append(await self._one(proc, cmd))
                    results.append(await self._one(proc, "end"))
                saved = None
                if save:
                    res = await self._one(proc, self.cfg.save_command)
                    results.append(res)
                    saved = "error_detected" not in res
        errors = [r["error_detected"] for r in results if r.get("error_detected")]
        self._emit("info", detail=f"config applied ({len(commands)} cmd"
                                  f"{'s' if len(commands) != 1 else ''}"
                                  + (f" in '{context}'" if context else "")
                                  + (", saved to flash" if save else "") + ")")
        return {"results": results, "saved": saved,
                "errors": errors, "ok": not errors}

    # -- introspection ------------------------------------------------------

    async def cli_help(self, tokens: str = "", context: Optional[str] = None) -> dict:
        conn = await self._ensure()
        async with self._lock:
            async with conn.create_process(term_type="vt100") as proc:
                await self._prepare(proc, force_enable=True)
                if context:
                    await self._one(proc, "configuration")
                    await self._one(proc, context)
                probe = (tokens.strip() + " ?").strip() if tokens.strip() else "?"
                self._emit("tx", data=probe)
                self._emit("status", state="busy", detail=f"discovering: {probe}")
                proc.stdin.write(probe)                 # no newline
                help_text = await self._read_help(proc, timeout=self.cfg.command_timeout)
                proc.stdin.write("\x15")                # Ctrl-U: clear line
                await self._read_until_idle(proc, quiet=0.3)
                if context:
                    await self._one(proc, "end")
                self._emit("status", state="idle")
        return {"tokens": tokens, "context": context,
                "output": _clean(help_text, "", self._prompt, self._pager)}

    async def _read_help(self, proc, timeout: int) -> str:
        buf: list[str] = []
        try:
            async with asyncio.timeout(timeout):
                while True:
                    try:
                        chunk = await asyncio.wait_for(proc.stdout.read(4096),
                                                       timeout=0.6)
                    except asyncio.TimeoutError:
                        break
                    if not chunk:
                        break
                    buf.append(chunk)
                    self._emit("rx", data=chunk)
                    if self._pager.search(chunk):
                        proc.stdin.write(" ")
                        self._emit("info", detail="pager: sent space")
        except asyncio.TimeoutError:
            pass
        return "".join(buf)

    # -- low-level reads ----------------------------------------------------

    async def _read_until_prompt(self, proc, timeout: int) -> str:
        buf: list[str] = []
        tail = ""
        try:
            async with asyncio.timeout(timeout):
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    buf.append(chunk)
                    self._emit("rx", data=chunk)
                    tail = (tail + chunk)[-512:]
                    if self._pager.search(tail):
                        proc.stdin.write(" ")
                        self._emit("info", detail="pager: sent space")
                        tail = ""
                        continue
                    m = self._prompt.search(tail)
                    if m:
                        self._last_prompt = m.group(0).strip()
                        break
        except asyncio.TimeoutError:
            self._emit("status", state="error", detail="command timed out")
        return "".join(buf)

    async def _read_until_idle(self, proc, quiet: float = 0.4) -> str:
        buf: list[str] = []
        while True:
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(4096), timeout=quiet)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            buf.append(chunk)
        return "".join(buf)

    # -- device info (for the banner) ---------------------------------------

    async def device_info(self) -> dict:
        from .parsers import generic_keyvalue
        info: dict = {"host": self.cfg.host, "port": str(self.cfg.port),
                      "username": self.cfg.username}
        if self._last_prompt:
            info["hostname"] = self._last_prompt.split(":")[0].strip()

        async def fields(cmd: str) -> dict:
            try:
                r = await self.run(cmd)
                return generic_keyvalue(r["output"]).get("fields", {})
            except Exception as exc:
                log.debug("device_info %r failed: %s", cmd, exc)
                return {}

        for k, v in (await fields("show version")).items():
            lk = k.lower()
            if "version" in lk and "firmware" not in info:
                info["firmware"] = v
            if ("model" in lk or "product" in lk) and "model" not in info:
                info["model"] = v
        for k, v in (await fields("show system characteristics")).items():
            lk = k.lower()
            if lk in ("name", "system name", "server name") and "name" not in info:
                info["name"] = v
            if "location" in lk and "location" not in info:
                info["location"] = v
            if ("model" in lk or "type" in lk) and "model" not in info:
                info["model"] = v
        ip_re = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
        for v in (await fields("show system ip")).values():
            m = ip_re.search(v)
            if m:
                info["ip"] = m.group(1)
                break
        st = await fields("show system status")
        if "System Uptime" in st:
            info["uptime"] = st["System Uptime"]
        if "Current OnBoard Temp" in st:
            info["temp"] = st["Current OnBoard Temp"]
        return info


def _find_error(text: str) -> Optional[str]:
    m = _ERROR_RE.search(text or "")
    return m.group(0) if m else None


def _clean(text: str, command: str, prompt: "re.Pattern", pager: "re.Pattern") -> str:
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if command and lines and command.strip() in lines[0]:
        lines = lines[1:]
    lines = [ln for ln in lines
             if not prompt.search(ln) and not pager.search(ln)]
    return "\n".join(lines).strip("\n")
