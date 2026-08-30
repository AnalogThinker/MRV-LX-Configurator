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

## Interface preview

<p align="center">
  <a href="docs/screenshots/classic-port-config.png">
    <img src="docs/screenshots/classic-port-config.png" alt="MRV LX Configurator interface" width="1200">
  </a>
</p>

The Classic Port Configuration interface loads the selected port's current settings, tracks modified fields, applies only pending changes, and can persist the running configuration to flash.

## Current features

### Device connection

- Connect to any reachable MRV LX device by IP address or hostname.
- Editable SSH port, username, password, and enable password.
- Optional environment variables provide connection-form defaults.
- Displays device information such as firmware, uptime, temperature, connection target, and hostname when available.
- Supports multiple browser/device sessions through per-connection session tokens.
- Shows live connection activity while the initial device profile is loading.

### Classic Port Configuration

The primary configuration interface follows the functional organization of the original Java application while using the modern SSH and CLI backend.

- Select an asynchronous port from the live port summary.
- Load the port's current configuration into a form.
- Prepopulate form controls with values reported by the MRV.
- Supply baseline values for stable settings such as speed, data bits, stop bits, parity, flow control, and common enabled/disabled states.
- Preserve an MRV-reported current value even when the value is not part of the local baseline.
- Organize settings into feature tabs:
  - Console
  - TCP / Telnet / SSH
  - Authentication
  - Data Buffer
  - Modem / APD
  - RS-485
  - Signal / Alarms
  - Attached Devices
  - Advanced
- Mark edited fields and display the number of pending changes.
- Apply only fields whose values changed.
- Disable the form while an operation is running.
- Reload the selected port after applying changes.
- Compare reloaded values with the requested values for verification.
- Tolerate unsupported read views without blocking the complete port profile.

The current Classic form focuses first on commonly used console-port fields. Additional feature tabs are being populated and validated against real MRV command output.

### Advanced command explorer

The recursive, introspection-driven command builder remains available as an advanced interface for uncommon, firmware-specific, or not-yet-mapped settings.

- Browse settings organized into functional categories:
  - Serial port
  - Access and connection
  - Attached device
  - Miscellaneous and advanced
- Recursively discover command paths using the device's context-sensitive `?` help.
- Support commands with variable depth, for example:

```text
tcp
  destination
    <address>
```

- Detect `<cr>` to determine when the current command path is complete.
- Support keyword dropdowns, finite enumerated values, free-text placeholders, and wrapped help descriptions.
- Show the generated in-context CLI command before applying it.
- Detect and report MRV CLI errors such as `Syntax Error`, `Invalid input`, and incomplete commands.

### Configuration persistence

The interface distinguishes between the MRV running configuration and flash configuration:

- **Apply to running config** applies the selected changes to the active configuration. The changes are lost after a reboot unless the running configuration is later saved to flash.
- **Apply and persist to flash** applies the selected changes and then saves the complete running configuration to flash.
- **Persist all running changes to flash** runs `save configuration flash` and saves every currently active unsaved change on the device, not only changes made in the current form operation.

The standalone flash-persistence action requires confirmation.

### Read-only device information

Read actions are grouped into collapsed categories:

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

The output area is grouped with the read-only controls and kept separate from configuration results.

### Live SSH activity

- Displays commands sent to the MRV and output received from the MRV.
- Shows connection, busy, idle, and error states.
- Handles MRV paged output automatically.
- Advances each distinct pager prompt once and stops when the final CLI prompt appears.
- Includes a pager safety limit to prevent runaway input.
- Normalizes CR, LF, and CRLF terminal line endings into readable multiline output.
- Buffers character-by-character SSH output into readable blocks.
- Removes ANSI screen-control sequences and terminal bell characters from the browser activity display.
- Retains extended backend and browser event history for troubleshooting.

### Raw terminal

An xterm.js terminal remains available as an advanced/manual escape hatch. The terminal uses a separate SSH connection from the application control channel.

## SSH architecture

The tested MRV LX firmware only initializes the first interactive process channel on an SSH transport as a complete, functional CLI session.

The application therefore uses the following architecture:

```text
Browser session
├── Persistent control SSH transport
│   └── One persistent CLI process channel
│       ├── Startup information
│       ├── Read commands
│       ├── Port-profile loading
│       ├── Configuration writes
│       └── Save-to-flash operations
│
├── Disposable introspection SSH sessions
│   └── Context-sensitive "?" help discovery
│
└── Separate raw-terminal SSH connection
    └── xterm.js interactive terminal
```

Normal reads and writes are serialized through the persistent CLI channel. This avoids reconnecting for every command while remaining compatible with the MRV firmware.

Introspection uses disposable SSH sessions because the MRV leaves a partially typed help command in its line-editing buffer after `?`, and the tested firmware does not reliably clear that buffer with `Ctrl+U`.

Privilege state is isolated per CLI process. A disposable discovery session cannot cause the persistent control session to incorrectly assume that it is already in superuser mode.

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
| Port detail | Requires a final view, such as `characteristics`, `status`, `tcp`, or `users` |

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
│   ├── port_schema.py
│   ├── sessions.py
│   ├── ssh.py
│   └── static/
│       └── index.html
├── docs/
│   └── screenshots/
│       └── classic-port-config.png
├── install.sh
├── requirements.txt
└── README.md
```

`port_schema.py` defines the Classic form tabs, field metadata, baseline values, CLI command templates, output aliases, and conservative port-profile parsing used by the form interface.

## Installation on Debian or Ubuntu

### Clone and install

Run as root or with `sudo` inside the target VM, server, or LXC:

```bash
git clone https://github.com/AnalogThinker/MRV-LX-Configurator.git
cd MRV-LX-Configurator
sudo bash install.sh
```

The installer:

1. installs Python, pip, venv, and required system packages;
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
  app/port_schema.py \
  app/sessions.py \
  app/events.py
```

No output means the files passed syntax validation.

### Validate the YAML command registry

```bash
cd /opt/lxconsole
.venv/bin/python -c "import yaml; yaml.safe_load(open('app/commands.yaml')); print('YAML OK')"
```

### Classic form values do not populate

Review the Live SSH Activity panel and the port-profile response. The Classic form maps labels reported by commands such as:

```text
show port async 1 characteristics
show port async 1 tcp
show port async 1 login
show port async 1 apd
```

Unsupported views are recorded but do not prevent other values from loading. Additional firmware-specific labels may need to be added as aliases in `app/port_schema.py`.

### Commands return syntax errors

MRV commands can require additional command levels. For example:

```text
show port async 1
```

is incomplete on the tested firmware, while the following is valid:

```text
show port async 1 characteristics
```

Use the Advanced command explorer or Raw Terminal to inspect the live command tree when validating a new field mapping.

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
- Use a VPN, authenticated reverse proxy, or another approved access control if remote access is required.
- SSH host-key verification is currently disabled with `known_hosts=None` for compatibility and ease of deployment.
- The application intentionally enables legacy SSH algorithms required by the MRV hardware.
- Passwords and enable passwords should never be written to application logs.

## Planned improvements

- Complete and validate the remaining Classic form tabs against live MRV output.
- Expand exact read-label aliases and CLI write mappings in `port_schema.py`.
- Prefetch and cache firmware-specific option sets where local baseline values are insufficient.
- Improve structured parsers for additional read-only views.
- Add optional saved-device profiles.
- Add SSH host-key pinning.
- Add authentication or reverse-proxy deployment guidance.
- Explore portable Windows packaging for technician use.

## Disclaimer

This is an independent community project and is not affiliated with or supported by MRV Communications, Oracle, or the original Java application authors. Test configuration changes carefully before using the tool on production equipment.
