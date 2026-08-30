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
    """Parse LX context help, preserving wrapped descriptions and enums."""
    entries: list[dict] = []
    current: dict | None = None
    accepts_cr = False

    for raw in text.splitlines():
        if not raw.strip() or "Type a key to continue" in raw:
            continue

        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()

        # LX command entries begin near the left margin and separate the token
        # from its description with at least two spaces. Deeply indented lines
        # are wrapped continuations, even if they contain a single word such
        # as "established".
        match = re.match(r"^(\S+)(?:\s{2,}(.*))?$", stripped)
        token = match.group(1) if match else ""
        desc = (match.group(2) or "").strip() if match else ""

        if indent < 8 and token == "<cr>":
            accepts_cr = True
            current = None
            continue

        is_placeholder = bool(
            indent < 8 and token.startswith("<") and token.endswith(">")
        )
        is_option = bool(
            indent < 8
            and desc
            and re.fullmatch(r"[A-Za-z0-9][\w+.\-/]*", token)
        )

        if is_placeholder or is_option:
            current = {
                "token": token,
                "desc": desc,
                "placeholder": is_placeholder,
            }
            entries.append(current)
            continue

        if current is not None:
            current["desc"] = " ".join(
                part for part in (current["desc"], stripped) if part
            )

    options: list[dict] = []
    placeholders: list[dict] = []

    for entry in entries:
        token = entry["token"]
        desc = entry["desc"]

        if not entry["placeholder"]:
            options.append({"value": token, "desc": desc})
            continue

        enum_match = re.search(r"\(([^()]*,[^()]*)\)", desc)
        if enum_match:
            values = [
                value.strip()
                for value in enum_match.group(1).split(",")
                if value.strip()
            ]
            if values:
                options.extend({"value": value, "desc": ""} for value in values)
                continue

        placeholders.append({"value": token, "desc": desc})

    return {
        "type": "cli_help",
        "options": options,
        "placeholders": placeholders,
        "freeform": bool(placeholders),
        "accepts_cr": accepts_cr,
    }


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
