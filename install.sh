#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  My Work Log — one-command install for Linux
#    bash install.sh            install / update (safe to run again)
#    bash install.sh --yes      no questions (use detected values)
#    bash install.sh --uninstall
# ─────────────────────────────────────────────────────────────
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
YES=""; [ "$1" = "--yes" ] && YES="--yes"
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

if [ "$1" = "--uninstall" ]; then
  step "Removing My Work Log automation"
  (crontab -l 2>/dev/null | grep -vF "$DIR/" | grep -v "^# My Work Log" ) | crontab - && ok "cron entries removed"
  if [ -f /etc/systemd/system/my-work-log-shutdown.service ]; then sudo bash "$DIR/install_shutdown_hook.sh" --remove; fi
  pkill -f "$DIR/server.py" 2>/dev/null || pkill -f "python.* server.py" 2>/dev/null || true
  ok "done — your data (raw/, output/, config.yaml …) is still in $DIR"
  exit 0
fi

echo "═══════════════════════════════════════════════"
echo "  My Work Log — installer"
echo "═══════════════════════════════════════════════"

# 1. Python + PyYAML ───────────────────────────────────────────
step "1/6  Python"
command -v python3 >/dev/null || { echo "  Python 3 is required. Ubuntu/Debian:  sudo apt install python3"; exit 1; }
PY="$(command -v python3)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "  Python 3.9 or newer is required."; exit 1; }
if ! "$PY" -c "import yaml" 2>/dev/null; then
  if [ -x "$DIR/.venv/bin/python" ] && "$DIR/.venv/bin/python" -c "import yaml" 2>/dev/null; then
    PY="$DIR/.venv/bin/python"
  elif python3 -m venv "$DIR/.venv" >/dev/null 2>&1 && "$DIR/.venv/bin/pip" install -q pyyaml; then
    PY="$DIR/.venv/bin/python"
  elif command -v apt-get >/dev/null && sudo apt-get install -y -q python3-yaml >/dev/null; then
    :
  else
    python3 -m pip install --user -q pyyaml 2>/dev/null || python3 -m pip install --user -q --break-system-packages pyyaml
  fi
fi
"$PY" -c "import yaml" || { echo "  Could not install PyYAML."; exit 1; }
echo "$PY" > "$DIR/.python"
ok "$("$PY" --version) ($PY)"

# 2. What this PC has ─────────────────────────────────────────
step "2/6  Detecting tools"
command -v git >/dev/null && ok "git" || warn "git not found — commits won't be logged (sudo apt install git)"
if command -v claude >/dev/null || ls "$HOME"/.nvm/versions/node/*/bin/claude "$HOME/.local/bin/claude" >/dev/null 2>&1; then
  ok "Claude Code — AI summaries on"
else
  warn "Claude Code not found — summaries use a simple built-in draft. For AI summaries:"
  warn "  npm install -g @anthropic-ai/claude-code   then run:  claude   (sign in once)"
fi
for b in google-chrome chromium microsoft-edge BraveSoftware/Brave-Browser; do [ -d "$HOME/.config/$b" ] && ok "browser: $b"; done
{ [ -d "$HOME/.mozilla/firefox" ] || [ -d "$HOME/snap/firefox" ]; } && ok "browser: firefox"
[ -d "$HOME/.config/Code" ] && ok "VS Code"

# 3. Settings ─────────────────────────────────────────────────
step "3/6  Your settings"
"$PY" setup_config.py $YES

if [ -n "$WORKLOG_SKIP_SYSTEM" ]; then ok "WORKLOG_SKIP_SYSTEM set — not touching cron, systemd or the dashboard (test mode)"; exit 0; fi

# 4. Start-up + late-night safety nets (cron) ─────────────────
step "4/6  Automation"
if ! grep -q HISTTIMEFORMAT "$HOME/.bashrc" 2>/dev/null; then
  printf '\n# My Work Log: keep a time on every terminal command\nexport HISTTIMEFORMAT="%%F %%T "\n' >> "$HOME/.bashrc"
  ok "terminal history timestamps turned on (~/.bashrc)"
fi
if command -v crontab >/dev/null; then
  ENVP='PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin'
  { crontab -l 2>/dev/null | grep -vF "$DIR/" | grep -v "^# My Work Log" || true
    echo "# My Work Log ($DIR): start the dashboard + catch up a missed day after boot; save + email at 23:50 if still on"
    echo "@reboot sleep 30 && \"$DIR/start.sh\" --no-open >> \"$DIR/daily.log\" 2>&1; $ENVP \"$PY\" \"$DIR/session.py\" boot >> \"$DIR/daily.log\" 2>&1"
    echo "50 23 * * * $ENVP \"$PY\" \"$DIR/session.py\" fallback >> \"$DIR/daily.log\" 2>&1"
  } | crontab -
  ok "dashboard starts with the PC; catch-up after boot; 23:50 safety run"
else
  warn "cron not found — start the dashboard yourself with ./start.sh"
fi

# 5. Save my day at shutdown (systemd) ────────────────────────
step "5/6  Save my day when the PC shuts down"
if command -v systemctl >/dev/null; then
  echo "  This needs your password once (a small system service)."
  if sudo bash "$DIR/install_shutdown_hook.sh" --python "$PY"; then ok "installed"; else warn "skipped — run later: sudo bash \"$DIR/install_shutdown_hook.sh\""; fi
else
  warn "systemd not found — your day is saved by the start-up catch-up and the 23:50 run instead"
fi

# 6. Dashboard ────────────────────────────────────────────────
step "6/6  Dashboard"
chmod +x "$DIR"/*.sh
"$DIR/start.sh"
echo
echo "  Done. Open http://127.0.0.1:8765  →  Settings & help  →  connect your Google Sheet (2 minutes)."
