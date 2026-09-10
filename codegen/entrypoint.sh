#!/bin/sh
set -e

set -- uvicorn app.main:criar_aplicacao --factory --host 0.0.0.0 --port "${PORT:-8000}" --log-config logging.json

if [ "${UVICORN_RELOAD:-false}" = "true" ]; then
    set -- "$@" --reload
fi

exec "$@"
