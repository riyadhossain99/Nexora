#!/usr/bin/env bash
set -e

echo "==> Running database migrations..."
python backend/manage.py migrate --noinput

echo "==> Starting WhatsApp Node bridge on port 3001..."
node backend/whatsapp/index.js &

echo "==> Starting Gunicorn on port ${PORT:-8000}..."
exec gunicorn nexora.wsgi:application \
    --chdir backend \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 1 \
    --threads 4 \
    --timeout 120
