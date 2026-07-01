#!/usr/bin/env sh
set -eu

mkdir -p "${LOG_DIR:-/app/logs}" \
    "${FEED_DIR:-/app/feeds}" \
    "${EXPORT_DIR:-/app/exports}" \
    "${FILE_IMPORT_DIR:-/app/storage/file-import}" \
    /app/data

exec "$@"
