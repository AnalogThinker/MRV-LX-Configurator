"""parsers.py — turn raw LX CLI text into structured data (the XmlModel stand-in)."""

from __future__ import annotations

import re
from typing import Callable

_SECTION = re.compile(r"-{2,}\s*([A-Z][A-Z ]+?)\s*-{2,}")
_BANNER = re.compile(r"^-{2,}[A-Z ]*-*$|^[A-Z ]+-{2,}[A-Z ]*$|^-{3,}$")


def _pairs(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in text.split("\n"):
        tokens = [t for t in re.split(r"\s{2,}", line.strip()) if t]
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.endswith(":"):
                key = tok[:-1].strip()
                nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
                if nxt and not nxt.endswith(":") and not _BANNER.match(nxt):
                    out.append((key, nxt.strip()))
                    i += 2
                    continue
                out.append((key, ""))
            i += 1
    return out


def port_async_detail(text: str) -> dict:
    pairs = _pairs(text)
    fields = dict(pairs)
    sections = [s.strip() for s in _SECTION.findall(text)]
    title = f"Port {fields.get('Port Number','?')} — {fields.get('Port Name','')}".strip(" —")
    return {"type": "keyvalue", "title": title, "sections": sections,
            "fields": fields, "rows": [[k, v] for k, v in pairs]}


def port_async_summary(text: str) -> dict:
    columns = ["Port", "Port Name", "Access", "Speed",
               "TCP Port", "SSH port", "Device"]
    rows: list[dict] = []
    for line in text.split("\n"):
        toks = line.strip().split()
        if len(toks) == 7 and toks[0].isdigit():
            rows.append(dict(zip(columns, toks)))
    return {"type": "table", "columns": columns, "rows": rows, "count": len(rows)}


def generic_keyvalue(text: str) -> dict:
    pairs = _pairs(text)
    sections = [s.strip() for s in _SECTION.findall(text)]
    return {"type": "keyvalue", "title": "", "sections": sections,
            "fields": dict(pairs), "rows": [[k, v] for k, v in pairs]}


def cli_help(text: str) -> dict:
    options: list[dict] = []
    placeholders: list[dict] = []
    accepts_cr = False
    for raw in text.split("\n"):
        if not raw.strip() or "Type a key to continue" in raw:
            continue
        indent = len(raw) - len(raw.lstrip())
        s = raw.strip()
        parts = re.split(r"\s{2,}", s, maxsplit=1)
        kw = parts[0].strip()
        desc = parts[1].strip() if len(parts) > 1 else ""
        if kw == "<cr>":
            accepts_cr = True
            continue
        if kw.startswith("<") and kw.endswith(">"):
            placeholders.append({"value": kw, "desc": desc})
            continue
        if not desc and indent >= 8:
            continue
        if re.match(r"^[A-Za-z0-9][\w+.\-/]*$", kw):
            options.append({"value": kw, "desc": desc})
    return {"type": "cli_help", "options": options, "placeholders": placeholders,
            "freeform": bool(placeholders), "accepts_cr": accepts_cr}


REGISTRY: dict[str, Callable[[str], dict]] = {
    "port_async_detail": port_async_detail,
    "port_async_summary": port_async_summary,
    "generic_keyvalue": generic_keyvalue,
    "cli_help": cli_help,
}


def parse(name: str, text: str) -> dict | None:
    fn = REGISTRY.get(name)
    if not fn:
        return None
    try:
        return fn(text)
    except Exception as exc:
        return {"type": "error", "error": f"{name} parser failed: {exc}"}
