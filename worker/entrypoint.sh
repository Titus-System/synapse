#!/bin/sh
set -e

set -- uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"

if [ "${UVICORN_RELOAD:-false}" = "true" ]; then
    set -- "$@" --reload
fi

exec "$@"
