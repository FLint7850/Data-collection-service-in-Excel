#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker не найден. Установите Docker Engine и повторите запуск." >&2
  echo "Debian/Ubuntu: https://docs.docker.com/engine/install/" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin не найден. Обновите Docker Engine/Compose." >&2
  exit 1
fi

mkdir -p data logs exports feeds storage/file-import backups

if [ ! -f .env ]; then
  cp .env.production.example .env
  SECRET="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  python3 - <<PY
from pathlib import Path
p = Path('.env')
s = p.read_text(encoding='utf-8')
s = s.replace('FLASK_SECRET_KEY=replace-with-long-random-secret', f'FLASK_SECRET_KEY={SECRET}')
p.write_text(s, encoding='utf-8')
PY
  echo "Создан .env с новым FLASK_SECRET_KEY. Перед запуском поменяйте AUTH_DEFAULT_PASSWORD и SMTP-настройки."
  exit 0
fi

docker compose build
docker compose up -d
docker compose ps
