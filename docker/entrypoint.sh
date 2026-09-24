#!/bin/sh
set -eu
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then flask --app wsgi:app db upgrade; fi
exec "$@"
