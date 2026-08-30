"""Parsers for MRV LX CLI output and context-sensitive help."""
from __future__ import annotations
import re
from typing import Callable

_SECTION = re.compile(r"-{2,}\s*([A-Z][A-Z ]+?)\s*-{2,}")
_BANNER = re.compile(r"^-{2,}[A-Z ]*-*$|^[A-Z ]+-{2,}[A-Z ]*$|^-{3,}$")


def _pairs(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        tokens = [x for x in re.split(r"\s{2,}", line.strip()) if x]
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.endswith(":"):
                key = token[:-1].strip()
                value = tokens[index + 1] if index + 1 < len(tokens) else ""
                if value and not value.endswith(":") and not _BANNER.match(value):
                    out.append((key, value.strip()))
                    index += 2
                    continue
                out.append((key, ""))
            index += 1
    return out


def port_async_detail(text: str) -> dict:
    pairs = _pairs(text)
    fields = dict(pairs)
    title = f"Port {fields.get('Port Number', '?')} - {fields.get('Port Name', '')}".strip(" -")
    return {"type": "keyvalue", "title": title,
            "sections": [x.strip() for x in _SECTION.findall(text)],
            "fields": fields, "rows": [[k, v] for k, v in pairs]}


def port_async_summary(text: str) -> dict:
    columns = ["Port", "Port Name", "Access", "Speed", "TCP Port", "SSH port", "Device"]
    rows = []
    for line in text.splitlines():
        tokens = line.strip().split()
        if len(tokens) == 7 and tokens[0].isdigit():
            rows.append(dict(zip(columns, tokens)))
    return {"type": "table", "columns": columns, "rows": rows, "count": len(rows)}


def generic_keyvalue(text: str) -> dict:
    pairs = _pairs(text)
    return {"type": "keyvalue", "title": "",
            "sections": [x.strip() for x in _SECTION.findall(text)],
            "fields": dict(pairs), "rows": [[k, v] for k, v in pairs]}


def cli_help(text: str) -> dict:
    """Parse keyword, placeholder, wrapped-description, enum and <cr> help."""
    entries = []
    current = None
    accepts_cr = False
    for raw in text.splitlines():
        if not raw.strip() or "Type a key to continue" in raw:
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        match = re.match(r"^(\S+)(?:\s{2,}(.*))?$", stripped)
        token = match.group(1) if match else ""
        desc = (match.group(2) or "").strip() if match else ""
        if indent < 8 and token == "<cr>":
            accepts_cr = True
            current = None
            continue
        placeholder = indent < 8 and token.startswith("<") and token.endswith(">")
        option = indent < 8 and bool(desc) and bool(re.fullmatch(r"[A-Za-z0-9][\w+.\-/]*", token))
        if placeholder or option:
            current = {"token": token, "desc": desc, "placeholder": placeholder}
            entries.append(current)
        elif current is not None:
            current["desc"] = " ".join(x for x in (current["desc"], stripped) if x)

    options, placeholders = [], []
    for entry in entries:
        token, desc = entry["token"], entry["desc"]
        if not entry["placeholder"]:
            options.append({"value": token, "desc": desc})
            continue
        enum_match = re.search(r"\(([^()]*,[^()]*)\)", desc)
        if enum_match:
            values = [x.strip() for x in enum_match.group(1).split(",") if x.strip()]
            if values:
                options.extend({"value": value, "desc": "", "enum": True} for value in values)
                continue
        placeholders.append({"value": token, "desc": desc})
    return {"type": "cli_help", "options": options,
            "placeholders": placeholders, "freeform": bool(placeholders),
            "accepts_cr": accepts_cr}


REGISTRY: dict[str, Callable[[str], dict]] = {
    "port_async_detail": port_async_detail,
    "port_async_summary": port_async_summary,
    "generic_keyvalue": generic_keyvalue,
    "cli_help": cli_help,
}


def parse(name: str, text: str) -> dict | None:
    function = REGISTRY.get(name)
    if not function:
        return None
    try:
        return function(text)
    except Exception as exc:
        return {"type": "error", "error": f"{name} parser failed: {exc}"}
