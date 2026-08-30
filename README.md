# MRV LX Configurator

A modern, self-hosted web interface for managing **MRV / Notus LX Series console servers**, developed and tested against an **LX-4048T-101AC** running firmware 5.3.7.

The project replaces the deprecated Java 1.5 configuration applet with a browser-based interface backed by the MRV CLI over standard SSH.

> **Project status:** Active development with successful real-device testing.

## Why this project exists

Older MRV LX devices shipped with a Java applet that depended on obsolete browser plugins, Java 1.5-era components, J2SSH, and a proprietary GUI protocol. Modern browsers can no longer run that interface.

MRV LX Configurator provides a modern replacement using:

- FastAPI
- AsyncSSH
- HTML, CSS, and JavaScript
- xterm.js
- Server-Sent Events
- The supported MRV CLI over SSH port 22

The proprietary GUI-server protocol on TCP port 5040 is not used.

## Current features

### Device connection

- Connect to any reachable MRV LX device by IP address or hostname.
- Editable SSH port, username, password, and enable password.
- Defaults for the commonly used MRV credentials can be supplied through environment variables.
- Displays device information such as firmware, uptime, temperature, connection target, and hostname when available.
- Supports multiple browser/device sessions through per-connection session tokens.

### Guided port configuration

- Select an asynchronous port from the live port summary.
- Browse settings organized into functional categories:
  - Serial port
  - Access and connection
  - Attached device
  - Miscellaneous and advanced
- Recursively discovers command paths from the device using context-sensitive `?` help.
- Supports commands with variable depth, for example:

```text
tcp
  destination
    <address>
```

- Detects `<cr>` to determine when a command path is complete.
- Supports:
  - keyword dropdowns
  - finite enumerated values
  - free-text placeholders
  - wrapped help descriptions
- Shows the generated in-context CLI command before applying it.
- Detects and reports MRV CLI errors such as `Syntax Error`, `Invalid input`, and incomplete commands.

### Configuration persistence

The interface distinguishes between the MRV running configuration and flash configuration:

- **Apply to running config** applies the selected change to the active configuration. The change is lost after a reboot unless the running configuration is later saved to flash.
- **Apply and persist to flash** applies the selected change and then saves the complete running configuration to flash.
- **Persist all running changes to flash** runs `save configuration flash` and saves every currently active unsaved change on the device.

### Read-only device information

Read actions are grouped into collapsible categories:

- System
- Network
- Ports
- Sessions and users
- Services
- Advanced

Port-specific read views support commands such as:

```text
show port async 1 characteristics
show port async 1 status
show port async 1 tcp
show port async 1 users
```

### Live SSH activity

- Displays commands sent to the MRV and output received from the MRV.
- Shows connection, busy, idle, and error states.
- Handles MRV paged output automatically.
- Normalizes terminal line endings for readable multiline output.
- Buffers character-by-character SSH output into readable blocks.
- Removes ANSI screen-control sequences and terminal bell characters from the activity display.
- Retains an extended event history for troubleshooting.

### Raw terminal

An xterm.js terminal is available as an advanced/manual escape hatch. The terminal uses a separate SSH connection from the application control channel.

## SSH architecture

The MRV LX firmware has an unusual SSH limitation: only the first interactive process channel on an SSH transport receives a complete, functional CLI session.

The application therefore uses the following architecture:

```text
Browser session
├── Persistent control SSH transport
│   └── One persistent CLI process channel
│       ├── Read commands
│       ├── Configuration writes
│       └── Save-to-flash operations
│
├── Disposable introspection SSH sessions
│   └── Context-sensitive "?" help discovery
│
└── Separate raw-terminal SSH connection
    └── xterm.js interactive terminal
```

Normal reads and writes are serialized through the persistent CLI channel. This avoids the delay of reconnecting for every command while remaining compatible with the MRV firmware.

Introspection uses disposable SSH sessions because the MRV leaves the partially typed help command in its line-editing buffer after `?`, and the tested firmware does not reliably clear that buffer with `Ctrl+U`.

## Confirmed MRV behavior

The following behavior has been confirmed against the real LX-4048T-101AC:

| Item | Confirmed behavior |
|---|---|
| SSH host keys | Device offers legacy `ssh-rsa` and `ssh-dss` host keys |
| Login | `InReach` / `access` enters the normal MRV CLI |
| User prompt | `InReach:0 >` |
| Superuser | `enable`, followed by the enable password |
| Superuser prompt | `InReach:0 >>` |
| Configuration mode | `configuration` produces `Config:0 >>` |
| Async-port context | `port async 1` produces `Async1:0 >>` |
| Exit to superuser | `end` |
| Save to flash | `save configuration flash` |
| Pager text | `Type a key to continue, q to quit` |
| System IP command | `show system ip status` |
| Port summary | `show port async summary` |

Example configuration transaction:

```text
enable
configuration
port async 1
speed 4800
end
save configuration flash
```

## Project layout

```text
MRV-LX-Configurator/
├── app/
│   ├── __init__.py
│   ├── commands.yaml
│   ├── events.py
│   ├── main.py
│   ├── parsers.py
│   ├── sessions.py
│   ├── ssh.py
│   └── static/
│       └── index.html
├── install.sh
├── requirements.txt
└── README.md
```

## Installation on Debian or Ubuntu

### Clone and install

Run as root or with `sudo` inside the target VM, server, or LXC:

```bash
git clone https://github.com/AnalogThinker/MRV-LX-Configurator.git
cd MRV-LX-Configurator
sudo bash install.sh
```

The installer:

1. installs Python, pip, venv, and required packages;
2. installs the application under `/opt/lxconsole` by default;
3. creates a Python virtual environment;
4. installs `requirements.txt`;
5. creates and enables the `lxconsole` systemd service;
6. starts the application on port 8080.

Open:

```text
http://<server-or-lxc-ip>:8080
```

### Install directly from the Git repository

If `install.sh` is already available locally:

```bash
sudo REPO=https://github.com/AnalogThinker/MRV-LX-Configurator.git bash install.sh
```

### Optional installer overrides

```bash
sudo \
  DEST=/opt/lxconsole \
  PORT=8080 \
  SERVICE=lxconsole \
  LX_HOST=192.168.0.50 \
  LX_USER=InReach \
  LX_PASSWORD=access \
  LX_ENABLE_PASSWORD=system \
  bash install.sh
```

## Updating an existing Git-managed installation

```bash
cd /opt/lxconsole
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
systemctl restart lxconsole
systemctl status lxconsole --no-pager
```

After updating, force-refresh the browser to bypass cached HTML and JavaScript:

```text
Ctrl+F5
```

## Manual development run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Environment variables

| Variable | Default | Purpose |
|---|---:|---|
| `LX_HOST` | empty | Pre-fills the target MRV address |
| `LX_PORT` | `22` | Pre-fills the SSH port |
| `LX_USER` | `InReach` | Pre-fills the MRV username |
| `LX_PASSWORD` | `access` | Pre-fills the login password |
| `LX_ENABLE_PASSWORD` | `system` | Pre-fills the enable password |

These values are form defaults only. Users can change them in the connection dialog.

## Service management

```bash
systemctl status lxconsole
systemctl restart lxconsole
systemctl stop lxconsole
journalctl -u lxconsole -f -o cat
```

## Troubleshooting

### Confirm network reachability

From the application host:

```bash
ping <mrv-ip>
nc -vz <mrv-ip> 22
```

### Validate Python source

```bash
cd /opt/lxconsole
.venv/bin/python -m py_compile \
  app/ssh.py \
  app/main.py \
  app/parsers.py \
  app/sessions.py \
  app/events.py
```

No output means the files passed syntax validation.

### Validate the YAML command registry

```bash
cd /opt/lxconsole
.venv/bin/python -c "import yaml; yaml.safe_load(open('app/commands.yaml')); print('YAML OK')"
```

### Commands return syntax errors

Review the Live SSH Activity panel. MRV commands can require additional command levels. For example:

```text
show port async 1
```

is incomplete on the tested firmware, while the following is valid:

```text
show port async 1 characteristics
```

### Browser still shows the old interface

Use:

```text
Ctrl+F5
```

or clear the browser cache for the configurator address.

## Security notes

- The application is intended for trusted management networks.
- The current web interface does not provide built-in user authentication.
- Do not expose the application directly to the public internet.
- Use a VPN, authenticated reverse proxy, or other approved access control if remote access is required.
- SSH host-key verification is currently disabled with `known_hosts=None` for compatibility and ease of deployment.
- The application intentionally enables legacy SSH algorithms required by the MRV hardware.
- Passwords and enable passwords should never be written to application logs.

## Planned improvements

- Classic form-based port configuration inspired by the original Java interface.
- Preloaded current port values with dirty-field tracking.
- Apply only changed fields, then reload and verify returned values.
- Feature tabs for Console, TCP/Telnet/SSH, Authentication, Data Buffer, Modem/APD, RS-485, Signal/Alarms, Attached Devices, and Advanced.
- Firmware-aware caching of introspection results.
- Improved structured parsers for additional read-only views.
- Optional saved-device profiles.
- SSH host-key pinning.
- Authentication or reverse-proxy deployment guidance.
- Portable Windows packaging for technician use.

## Disclaimer

This is an independent community project and is not affiliated with or supported by MRV Communications, Oracle, or the original Java application authors. Test configuration changes carefully before using the tool on production equipment.
