#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
ROOT="$PWD"
PYTHON="$ROOT/backend/.venv/bin/python"

command -v node >/dev/null || { echo "Install Node.js LTS from https://nodejs.org/"; exit 1; }
if [ "${1:-}" = "setup" ]; then
    [ -x "$PYTHON" ] || python3 -m venv backend/.venv
    "$PYTHON" -m pip install -r backend/requirements.txt
    (cd backend/whatsapp && npm ci)
fi

if [ ! -x "$PYTHON" ] || [ ! -d backend/whatsapp/node_modules ]; then
    echo "Run: bash start.sh setup"
    exit 1
fi
[ -f backend/.env ] || cp backend/.env.example backend/.env
if ! "$PYTHON" backend/manage.py migrate --noinput; then
    echo "Start MySQL in XAMPP and check the DB_* values in backend/.env."
    echo "On a new computer, import database/setup.sql using phpMyAdmin first."
    exit 1
fi
if [ "${1:-}" = "setup" ]; then
    echo "Setup complete. Run: bash start.sh"
    exit 0
fi

node backend/whatsapp/index.js &
BRIDGE_PID=$!
"$PYTHON" backend/manage.py runserver 127.0.0.1:8000 &
BACKEND_PID=$!
trap 'kill "$BRIDGE_PID" "$BACKEND_PID" 2>/dev/null || true' EXIT
trap 'exit 0' INT TERM
echo "Website: http://127.0.0.1:8000/ — press Ctrl+C to stop both servers."
wait "$BACKEND_PID" "$BRIDGE_PID"
