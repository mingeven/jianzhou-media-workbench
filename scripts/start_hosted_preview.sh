#!/bin/sh
set -eu
: "${JIANZHOU_ADMIN_PASSWORD:?Set the administrator password in cloud secrets}"
: "${JIANZHOU_SECRET_KEY:?Set the encryption key in cloud secrets}"
test "${#JIANZHOU_ADMIN_PASSWORD}" -ge 16 && test "${#JIANZHOU_ADMIN_PASSWORD}" -le 512
test "${JIANZHOU_DATA_DIR}" = /var/lib/jianzhou
# A persistent disk can be mounted with root ownership by the host.
if test "$(id -u)" = 0; then
    chown 10001:10001 "$JIANZHOU_DATA_DIR"
    exec setpriv --reuid=10001 --regid=10001 --clear-groups sh "$0"
fi
test -w "$JIANZHOU_DATA_DIR"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8741}" --workers 1 --no-access-log
