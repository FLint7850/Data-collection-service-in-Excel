# Сервис сбора данных в Excel

Flask-сервис для обхода каталогов, поиска моделей/цен, сравнения новинок с XML-фидами, импорта Excel/CSV и выгрузки результатов в CSV.

## Что изменено в релизной версии

- Убраны runtime-файлы из поставки: `.git`, `.idea`, `__pycache__`, локальная `.env`, SQLite-база, логи, экспорты, кеши браузеров и импортированные файлы.
- Добавлен production-запуск через Docker Compose + Gunicorn.
- Добавлены `.dockerignore`, `Dockerfile`, `docker-compose.yml`, `gunicorn.conf.py`, `wsgi.py`, nginx-пример и скрипты деплоя/backup.
- Включены production-проверки: нельзя запустить `APP_ENV=production` с дефолтным `FLASK_SECRET_KEY` или паролем `admin` для первого пользователя.
- Добавлены secure cookie настройки, `ProxyFix` для работы за Nginx, ограничение размера загрузки и простая защита логина от перебора.
- Скачивание CSV переведено на безопасное разрешение пути внутри `exports`.
- SQLite-путь теперь можно задавать через `DATABASE_PATH`, runtime-папки создаются автоматически.
- Добавлены индексы для планировщика брендов, доноров по методу подключения и проектов по времени обновления.
- Основные зависимости отделены от тяжелых экспериментальных парсеров.

Подробный релизный запуск: `docs/RELEASE.md`.

## Локальный запуск в Windows

Дважды нажмите:

```text
START_PARSER.cmd
```

Или вручную:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Открыть:

```text
http://127.0.0.1:5000
```

## Публичный локальный запуск через xTunnel

```text
INSTALL_XTUNNEL.cmd
START_PUBLIC_PARSER.cmd
```

## Production на Debian/Ubuntu

```bash
cp .env.production.example .env
# поменять FLASK_SECRET_KEY и AUTH_DEFAULT_PASSWORD
mkdir -p data logs exports feeds storage/file-import backups
docker compose build
docker compose up -d
```

Приложение публикуется только на `127.0.0.1:5000`; домен и HTTPS лучше отдавать через Nginx. Пример: `deploy/nginx/parser.conf.example`.

## Важное ограничение запуска

Не ставьте `WEB_CONCURRENCY` больше `1`. Активные сканы, очереди, браузерные сессии и планировщик находятся в памяти приложения. Несколько процессов будут жить каждый со своим состоянием и могут дублировать плановые задачи. Для ускорения используйте:

- `GUNICORN_THREADS` для веб-запросов;
- `MAX_CRAWL_WORKERS_PER_SCAN` для потоков внутри одного проекта;
- `MAX_CONCURRENT_SCANS` для количества одновременных сканов;
- `NEWS_ENRICH_WORKER_COUNT` для обогащения новинок.

Для стабильного VPS начните с production-дефолтов из `.env.production.example`.
