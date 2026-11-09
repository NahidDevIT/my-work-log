#!/usr/bin/env bash
# My Work Log — run the whole day now: collect → AI summary → sheet → email, then keep the dashboard up.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
PY="$(cat .python 2>/dev/null || command -v python3)"
echo "== $(date '+%F %T') daily run"
"$PY" run_day.py --email "$@"
./start.sh --no-open >/dev/null
