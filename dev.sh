#!/usr/bin/env bash
# Run the LABKickstart server in development.
# Avoids `pip install -e .` (hatchling's editable install is unreliable here).
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "error: $VENV/bin/uvicorn not found." >&2
  echo "create the venv first:" >&2
  echo "  python3 -m venv $VENV && $VENV/bin/pip install -r requirements.txt" >&2
  exit 1
fi

exec env PYTHONPATH="$(pwd)/src" \
  "$VENV/bin/uvicorn" labkickstart.app:app \
    --host "$HOST" --port "$PORT" --reload "$@"
