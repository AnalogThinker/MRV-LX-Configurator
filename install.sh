#!/usr/bin/env bash
#
# install.sh — one-shot installer for LX Console (modern) on a Debian/Ubuntu LXC.
#
# What it does:
#   1. installs python3 + venv + pip (and git, if cloning)
#   2. copies (or git-clones) the app into /opt/lxconsole
#   3. creates a virtualenv and installs requirements
#   4. writes + enables a systemd service (auto-starts, restarts on failure)
#   5. prints the URL to open
#
# Run as root INSIDE the container:
#
#   # A) if you copied the project folder in (has app/ + requirements.txt):
#   cd lxconsole && sudo bash install.sh
#
#   # B) install straight from a git repo:
#   sudo REPO=https://github.com/you/lxconsole.git bash install.sh
#
# Optional environment overrides:
#   DEST=/opt/lxconsole   PORT=8080   SERVICE=lxconsole
#   LX_USER=InReach  LX_PASSWORD=access  LX_ENABLE_PASSWORD=system  LX_HOST=
#
set -euo pipefail

DEST="${DEST:-/opt/lxconsole}"
PORT="${PORT:-8080}"
SERVICE="${SERVICE:-lxconsole}"
REPO="${REPO:-}"
LX_USER="${LX_USER:-InReach}"
LX_PASSWORD="${LX_PASSWORD:-access}"
LX_ENABLE_PASSWORD="${LX_ENABLE_PASSWORD:-system}"
LX_HOST="${LX_HOST:-}"

log() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

if [[ $EUID -ne 0 ]]; then
  err "Please run as root (sudo bash install.sh)."; exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1) prerequisites -----------------------------------------------------------
log "Installing prerequisites (python3, venv, pip$( [[ -n "$REPO" ]] && echo ', git' ))…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip $( [[ -n "$REPO" ]] && echo git ) >/dev/null

# 2) place the app -----------------------------------------------------------
mkdir -p "$DEST"
if [[ -n "$REPO" ]]; then
  if [[ -d "$DEST/.git" ]]; then
    log "Updating existing repo in $DEST…"; git -C "$DEST" pull --ff-only
  else
    log "Cloning $REPO -> $DEST…"; git clone --depth 1 "$REPO" "$DEST"
  fi
elif [[ -d "$SRC_DIR/app" && -f "$SRC_DIR/requirements.txt" ]]; then
  log "Copying project from $SRC_DIR -> $DEST…"
  cp -r "$SRC_DIR/app" "$SRC_DIR/requirements.txt" "$DEST"/
  [[ -f "$SRC_DIR/README.md" ]] && cp "$SRC_DIR/README.md" "$DEST"/ || true
else
  err "No REPO set and no app/ found next to install.sh. Aborting."; exit 1
fi

if [[ ! -f "$DEST/app/main.py" ]]; then
  err "Expected $DEST/app/main.py not found. Check your source."; exit 1
fi

# 3) virtualenv + deps -------------------------------------------------------
log "Creating virtualenv and installing requirements…"
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --quiet --upgrade pip
"$DEST/.venv/bin/pip" install --quiet -r "$DEST/requirements.txt"

# 4) systemd service ---------------------------------------------------------
UNIT="/etc/systemd/system/${SERVICE}.service"
log "Writing systemd unit $UNIT…"
cat > "$UNIT" <<EOF
[Unit]
Description=LX Console (modern)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DEST
Environment=LX_USER=$LX_USER LX_PASSWORD=$LX_PASSWORD LX_ENABLE_PASSWORD=$LX_ENABLE_PASSWORD LX_HOST=$LX_HOST
ExecStart=$DEST/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

log "Enabling and starting service…"
systemctl daemon-reload
systemctl enable --now "$SERVICE" >/dev/null 2>&1 || systemctl restart "$SERVICE"

sleep 1
if systemctl is-active --quiet "$SERVICE"; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  log "Done ✅  Open:  http://${IP:-<container-ip>}:${PORT}"
  log "Manage:  systemctl status $SERVICE  |  journalctl -u $SERVICE -f"
else
  err "Service failed to start. Check: journalctl -u $SERVICE -e"
  exit 1
fi
