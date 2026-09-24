#!/usr/bin/env bash
# First run: creates .venv, installs dependencies and a browser. Then starts the app.
#   ./start.sh                 your radar
#   ./start.sh --demo [--lang zh]   the interface with made-up data, no X login or AI key
set -euo pipefail
cd "$(dirname "$0")"
DEMO=0
if [ "${1:-}" = "--demo" ]; then DEMO=1; shift; fi
PORT="${PORT:-$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 || true)}"
PORT="${PORT:-8796}"
if [ "$DEMO" = 0 ] && command -v lsof >/dev/null && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  (command -v open >/dev/null && open "http://127.0.0.1:$PORT") || (command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT") || true
  exit 0
fi
PY="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
  echo "Setting up (first run only)…"
  "$PY" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  .venv/bin/python -m playwright install chromium
fi
if [ "$DEMO" = 1 ]; then exec .venv/bin/python scripts/demo.py "$@"; fi
exec .venv/bin/python app.py
