#!/usr/bin/env bash
# My Work Log — "save my day when the PC shuts down" (Linux, systemd). install.sh runs this for you.
#   sudo bash install_shutdown_hook.sh [--python /path/to/python3]      install
#   sudo bash install_shutdown_hook.sh --remove                          remove
#
# Why a system service: desktop sessions get only a few seconds at shutdown; this service gets up to
# 150 s and is stopped *before* the network goes down, so the sheet write and the email still work.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$(logname 2>/dev/null || stat -c %U "$DIR")}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
UNIT=/etc/systemd/system/my-work-log-shutdown.service
PY="$(cat "$DIR/.python" 2>/dev/null || command -v python3)"
[ "$1" = "--python" ] && PY="$2"

if [ "$(id -u)" != 0 ]; then echo "Run with sudo:  sudo bash \"$0\""; exit 1; fi
if ! command -v systemctl >/dev/null; then echo "systemd not found — skipping (the start-up catch-up still saves your day)"; exit 0; fi
if [ "$1" = "--remove" ]; then
  systemctl disable --now my-work-log-shutdown.service 2>/dev/null || true
  rm -f "$UNIT"; systemctl daemon-reload; echo "Removed."; exit 0
fi

cat > "$UNIT" <<UNIT
[Unit]
Description=My Work Log - save my day to the sheet and email it when the PC shuts down
Wants=network-online.target
After=network-online.target NetworkManager.service systemd-resolved.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=$USER_NAME
Environment=HOME=$USER_HOME
Environment=PATH=$USER_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
WorkingDirectory=$DIR
ExecStart=/bin/true
ExecStop=/usr/bin/env "$PY" "$DIR/session.py" shutdown
TimeoutStopSec=150

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now my-work-log-shutdown.service >/dev/null 2>&1
echo "Installed: shutting down the PC now saves your day (and emails it after the end-of-day time)."
