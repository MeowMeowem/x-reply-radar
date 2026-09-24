#!/usr/bin/env bash
# First run: creates .venv, installs dependencies and a browser. Then starts the app.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 || true)}"
PORT="${PORT:-8796}"
if command -v lsof >/dev/null && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
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
exec .venv/bin/python app.py
