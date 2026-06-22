# Развёртывание

## 1. Подготовка окружения

```bash
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# При необходимости всех движков:
# .\.venv\Scripts\python.exe -m pip install -r requirements-all.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Linux:

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
# При необходимости всех движков:
# .venv/bin/python -m pip install -r requirements-all.txt
.venv/bin/python -m playwright install chromium
```

Скопируйте `.env.example` в `.env` и обязательно измените:

```env
FLASK_SECRET_KEY=случайная-длинная-строка
AUTH_DEFAULT_USERNAME=не-admin
AUTH_DEFAULT_PASSWORD=сложный-пароль
DATABASE_PATH=data/app.db
HOST=127.0.0.1
PORT=5055
PRODUCTION_THREADS=8
```

Если сайт работает только через HTTPS reverse proxy, установите:

```env
SESSION_COOKIE_SECURE=1
```

## 2. Запуск

```bash
python run_production.py
```

Используется Waitress: один процесс и несколько потоков. Это соответствует текущей архитектуре crawler/scheduler.

## 3. Reverse proxy

Снаружи рекомендуется Nginx или Apache, который проксирует запросы на `127.0.0.1:5055`, завершает HTTPS и ограничивает доступ к служебным файлам.

Пример Nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name parser.example.ru;

    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:5055;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}
```

`proxy_buffering off` и большой `proxy_read_timeout` нужны для SSE `/progress` и долгих операций.

## 4. Проверка после запуска

```bash
curl http://127.0.0.1:5055/api/health
```

Ожидаемый ответ:

```json
{"ok": true}
```

## 5. Обновление

1. Остановить процесс приложения.
2. Сделать резервную копию `.env` и `data/app.db`.
3. Заменить код.
4. Установить обновлённые зависимости.
5. Запустить `python run_production.py`.
6. Проверить `/api/health`, вход, проекты, фиды и SMTP-тест.

SQLite работает в WAL-режиме. Перед копированием БД лучше корректно остановить приложение, чтобы не переносить незавершённые `app.db-wal` и `app.db-shm`.
