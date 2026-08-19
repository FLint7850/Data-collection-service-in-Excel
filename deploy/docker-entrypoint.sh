#!/usr/bin/env sh
set -eu

mkdir -p "${FEED_DIR:-/app/feeds}" \
    "${EXPORT_DIR:-/app/exports}" \
    "${FILE_IMPORT_DIR:-/app/storage/file-import}" \
    "${PRICE_CONVERTER_DIR:-/app/storage/price-converter}" \
    "${ATTRIBUTE_ASSISTANT_DIR:-/app/storage/attribute-assistant}" \
    "${ATTRIBUTE_ASSISTANT_DIR:-/app/storage/attribute-assistant}/codex-users" \
    "${TMPDIR:-/tmp/parser}" \
    /app/data /app/profiles/projects

chmod 1777 "${TMPDIR:-/tmp/parser}" 2>/dev/null || true
chown -R app:app /app/data /app/feeds /app/exports /app/storage /app/profiles "${TMPDIR:-/tmp/parser}"

exec gosu app "$@"
