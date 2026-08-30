"""Classic port form schema and conservative MRV output parsing."""
from __future__ import annotations

import re
from typing import Any

# Stable values across the LX CLI family. Device discovery remains available
# in the Advanced tab for firmware-specific or uncommon settings.
PORT_SCHEMA: dict[str, Any] = {
    "tabs": [
        {"id": "console", "label": "Console"},
        {"id": "network", "label": "TCP / Telnet / SSH"},
        {"id": "authentication", "label": "Authentication"},
        {"id": "databuffer", "label": "Data Buffer"},
        {"id": "modem", "label": "Modem / APD"},
        {"id": "rs485", "label": "RS-485"},
        {"id": "signal", "label": "Signal / Alarms"},
        {"id": "device", "label": "Attached Devices"},
        {"id": "advanced", "label": "Advanced"},
    ],
    "fields": [
        {"id": "name", "tab": "console", "label": "Port name", "command": "name {value}", "type": "text", "aliases": ["Port Name", "Name"]},
        {"id": "speed", "tab": "console", "label": "Speed", "command": "speed {value}", "type": "select", "values": ["auto", "134", "200", "300", "600", "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"], "aliases": ["Speed", "Port Speed"]},
        {"id": "flowcontrol", "tab": "console", "label": "Flow control", "command": "flowcontrol {value}", "type": "select", "values": ["none", "xon", "rtscts", "both"], "aliases": ["Flow Control", "Flowcontrol"]},
        {"id": "bits", "tab": "console", "label": "Bits per character", "command": "bits {value}", "type": "select", "values": ["5", "6", "7", "8"], "aliases": ["Bits Per Character", "Data Bits", "Bits"]},
        {"id": "stopbits", "tab": "console", "label": "Stop bits", "command": "stopbits {value}", "type": "select", "values": ["1", "1.5", "2"], "aliases": ["Stop Bits", "Stopbits"]},
        {"id": "parity", "tab": "console", "label": "Parity", "command": "parity {value}", "type": "select", "values": ["none", "even", "odd", "mark", "space"], "aliases": ["Parity"]},
        {"id": "access", "tab": "console", "label": "Access", "command": "access {value}", "type": "select", "values": ["remote", "local", "dynamic", "databuffer", "sensor"], "aliases": ["Access", "Access Type"]},
        {"id": "autobaud", "tab": "console", "label": "Autobaud", "command": "autobaud {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["Autobaud"]},
        {"id": "autohangup", "tab": "console", "label": "Auto hangup", "command": "autohangup {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["Autohangup", "Auto Hangup"]},
        {"id": "idlebuffer", "tab": "console", "label": "Idle buffer", "command": "idlebuffer {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["Idle Buffer", "Idlebuffer"]},
        {"id": "transparency", "tab": "console", "label": "Transparent mode", "command": "transparency {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["Transparent Mode", "Transparency"]},
        {"id": "break", "tab": "console", "label": "Break", "command": "break {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["Break"]},
        {"id": "tcp_port", "tab": "network", "label": "TCP port", "command": "tcp port {value}", "type": "number", "aliases": ["TCP Port", "Tcp Port"]},
        {"id": "ssh_port", "tab": "network", "label": "SSH port", "command": "tcp ssh port {value}", "type": "number", "aliases": ["SSH Port", "Ssh Port"]},
        {"id": "rfc2217", "tab": "network", "label": "RFC2217", "command": "rfc2217 {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["RFC2217", "Rfc2217"]},
        {"id": "inbound_auth", "tab": "authentication", "label": "Inbound authentication", "command": "authentication inbound {value}", "type": "select", "values": ["local", "radius", "tacacs+", "none"], "aliases": ["Inbound Authentication"]},
        {"id": "outbound_auth", "tab": "authentication", "label": "Outbound authentication", "command": "authentication outbound {value}", "type": "select", "values": ["local", "radius", "tacacs+", "none"], "aliases": ["Outbound Authentication"]},
        {"id": "databuffer", "tab": "databuffer", "label": "Data buffer", "command": "databuffer {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["Databuffer", "Data Buffer"]},
        {"id": "apd_timeout", "tab": "modem", "label": "APD timeout", "command": "apd timeout {value}", "type": "number", "aliases": ["APD Timeout", "Apd Timeout"]},
        {"id": "apd_retry", "tab": "modem", "label": "APD retry", "command": "apd retry {value}", "type": "number", "aliases": ["APD Retry", "Apd Retry"]},
        {"id": "rs485", "tab": "rs485", "label": "RS-485 mode", "command": "rs485 {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["RS-485", "RS485"]},
        {"id": "signal", "tab": "signal", "label": "Signal notifications", "command": "signal {value}", "type": "select", "values": ["enabled", "disabled"], "aliases": ["Signal Notification", "Signal"]},
    ],
}


def parse_port_profile(outputs: dict[str, str], summary: dict[str, str] | None = None) -> dict[str, str]:
    """Map common MRV labels to classic form fields without inventing values."""
    result: dict[str, str] = {}
    lookup: dict[str, str] = {}
    for text in outputs.values():
        for line in text.splitlines():
            for match in re.finditer(r"(?:^|\s{2,})([A-Za-z][A-Za-z0-9 /()+_.-]*?):\s*(.*?)(?=\s{2,}[A-Za-z][A-Za-z0-9 /()+_.-]*?:|$)", line.strip()):
                key = re.sub(r"\s+", " ", match.group(1)).strip().lower()
                lookup[key] = match.group(2).strip()
    if summary:
        lookup.update({str(k).lower(): str(v) for k, v in summary.items()})
    for field in PORT_SCHEMA["fields"]:
        for alias in field.get("aliases", []):
            value = lookup.get(alias.lower())
            if value not in (None, "", "N/A"):
                result[field["id"]] = value
                break
    return result
