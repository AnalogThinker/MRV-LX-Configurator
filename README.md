# LX Console (modern) — replacement for the MRV LX-4048T Java applet

A self-contained web app that replaces the deprecated Java 1.5 applet
(`console.jnlp` + `asp.jar` + `j2ssh.jar`) for managing **MRV / Notus LX Series**
console servers (built/tested against an LX-4048T-101AC).

It drives the LX **CLI over standard SSH** and puts a modern web UI on top:
read dashboards with parsed tables, guided + manual configuration writes,
a live SSH activity log, an xterm.js terminal, and multi-device support.

---
## ⭐ Fastest install — one-shot script

# A) From the cloned/copied folder** (has `app/` + `requirements.txt`):
```bash
git clone https://github.com/AnalogThinker/MRV-LX-Configurator.git
cd MRV-LX-Configurator && sudo bash install.sh
```

# B) straight from a git repo:
```bash
sudo REPO=https://github.com/you/lxconsole.git bash install.sh
```

`install.sh` installs Python + deps, creates a venv, writes a **systemd
service**, starts it, and prints the URL. Optional overrides:

```bash
sudo DEST=/opt/lxconsole PORT=8080 SERVICE=lxconsole \
     LX_USER=InReach LX_PASSWORD=access LX_ENABLE_PASSWORD=system \
     bash install.sh
```

Manage it afterwards:
```bash
systemctl status lxconsole
journalctl -u lxconsole -f
```

---

## Features

- **Multi-device**: connect to any LX from a login screen (host/port/creds all
  editable, pre-filled with `InReach` / `access` / enable `system`). Device
  banner shows hostname, IP/model, firmware, uptime, temp. Disconnect button.
- **Read actions** with structured **table parsers** (system status/power, port
  summary, single-port detail).
- **Guided configuration** (introspection-driven): port → setting → value
  dropdowns pulled **live from the device**, so it adapts to 8- or 48-port units.
- **Manual configuration**: free-text hierarchical config.
- **Save to flash**: persists changes across reboot / power cycle.
- **Error detection**: scans device output for `Syntax Error` (and similar) and
  raises a red alert pointing to the verbose activity log.
- **Live SSH activity**: busy/idle/error dot + real-time `» sent / « received`
  wire log (Server-Sent Events).
- **Raw terminal**: xterm.js shell over WebSocket.

## Confirmed device facts (baked into the code)

| Item | Value |
|---|---|
| SSH host-key algos offered | `ssh-rsa`, `ssh-dss` only (legacy re-enabled) |
| Login | `InReach` / `access` → CLI (`InReach:0 >`) |
| Superuser | `enable` + `system` → `InReach:0 >>` |
| Config model | hierarchical: `configuration` → `port async N` (`Async1:0 >>`) → cmds → `end` |
| `set` alone | launches setup wizard (refused remotely) — NOT used |
| Persist | `save configuration flash` |

---

# Deploying on Proxmox (LXC)

## Prerequisites
- Proxmox VE 8.x with a Debian 12 LXC template:
  ```bash
  pveam update && pveam download local debian-12-standard_12.7-1_amd64.tar.zst
  ```
- The LX device reachable from the container's network (test `ping <lx-ip>`).

## Path A — turnkey Debian LXC via Proxmox VE Helper-Scripts
The community project gives you a clean Debian LXC fast; then run `install.sh`.

1. On the **Proxmox host shell**, create a Debian 12 LXC. Get the current
   command from the official site (URLs change over time):
   **https://community-scripts.github.io/ProxmoxVE/** → find **Debian** → copy
   its one-liner. (⚠️ review any community script before running it.)
2. `pct enter <CTID>`
3. Copy the project in (scp/git) and run `sudo bash install.sh`.

## Path B — manual LXC
On the **Proxmox host shell**:
```bash
pct create 950 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname lxconsole --cores 1 --memory 512 --swap 256 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --onboot 1
pct start 950 && pct enter 950
```
Then inside: copy the project in and `sudo bash install.sh`.
(For a static IP: `--net0 name=eth0,bridge=vmbr0,ip=192.168.0.20/24,gw=192.168.0.1`.)

## Manual run (no service)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
LX_HOST=192.168.0.50 uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Environment variables (all optional — just form defaults)
| Var | Default | Meaning |
|---|---|---|
| `LX_HOST` | *(empty)* | pre-fill host/IP |
| `LX_PORT` | `22` | pre-fill SSH port |
| `LX_USER` | `InReach` | pre-fill username |
| `LX_PASSWORD` | `access` | pre-fill password |
| `LX_ENABLE_PASSWORD` | `system` | pre-fill enable password |

## Troubleshooting
- **Can't reach LX**: `ping <lx-ip>` and `nc -vz <lx-ip> 22` from the container.
- **SSH handshake fails**: legacy `ssh-rsa`/`ssh-dss` already re-enabled; if your
  firmware differs, adjust the `LEGACY_*` lists in `app/ssh.py`.
- **Commands hang**: prompt regex expects an `InReach`-style prompt; override via
  `prompt_re` if your device's label differs.
- **"Syntax Error" alert**: a bad command was detected — open the Live SSH
  activity log to see exactly what was sent/received.
- **Logs**: `journalctl -u lxconsole -f`.

## Security notes
- Unauthenticated by design for trusted LAN/homelab use — put behind a reverse
  proxy with auth or a VPN if exposed.
- Host keys not pinned (`known_hosts=None`); add pinning if desired.
- Passwords are never written to the activity log.

---

## 🔁 Working across sessions (avoid losing work)

If you're iterating with an assistant whose workspace resets:
- **The delivered `lxconsole.zip` is your durable copy** — download it each time.
- **When you return after a reset, re-upload the latest zip** so work resumes
  instantly instead of being rebuilt.
- **Best**: push this folder to a **git repo** once; then `install.sh` can pull
  it (`REPO=...`) and you never depend on a temporary workspace.

## Project layout
```
lxconsole/
├── app/
│   ├── __init__.py
│   ├── ssh.py         # SSH transport, enable, config writes, introspection, error scan
│   ├── sessions.py    # multi-device session manager
│   ├── events.py      # SSE activity bus
│   ├── parsers.py     # CLI text -> tables + cli_help
│   ├── commands.yaml  # action registry
│   ├── main.py        # FastAPI app
│   └── static/index.html
├── install.sh         # one-shot installer (systemd)
├── requirements.txt
├── .gitignore
└── README.md
```
