#!/usr/bin/env bash
# My Work Log — start the dashboard (if it is not running) and open it in the browser.
cd "$(dirname "$0")"
PY="$(cat .python 2>/dev/null || command -v python3)"
if ! (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q ':8765 '; then
  nohup "$PY" server.py > server.log 2>&1 &
  sleep 1
fi
if [ "$1" != "--no-open" ]; then
  (xdg-open http://127.0.0.1:8765 || open http://127.0.0.1:8765) >/dev/null 2>&1 &
fi
echo "Dashboard: http://127.0.0.1:8765"
