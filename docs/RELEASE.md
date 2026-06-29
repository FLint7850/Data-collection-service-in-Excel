# Релизный запуск на Debian/Ubuntu

Проект подготовлен под запуск в Docker Compose: внутри контейнера Flask работает через Gunicorn, а наружу приложение отдается только на `127.0.0.1:5000`. Для домена и HTTPS ставится обычный Nginx на сервере.

Важно: приложение хранит активные сканы, очереди и планировщик в памяти процесса. Поэтому `WEB_CONCURRENCY` должен оставаться `1`. Ускорение делается потоками Gunicorn и настройками сканера, а не несколькими worker-процессами.

## 1. Первый запуск

```bash
cd /opt/excel-parser
cp .env.production.example .env
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

Вставьте результат в `FLASK_SECRET_KEY`, поменяйте `AUTH_DEFAULT_PASSWORD`, затем:

```bash
mkdir -p data logs exports feeds storage/file-import backups
docker compose build
docker compose up -d
docker compose logs -f parser
```

Или используйте готовый скрипт:

```bash
./scripts/deploy.sh
```

При первом запуске скрипт создаст `.env`, сгенерирует `FLASK_SECRET_KEY` и остановится, чтобы вы поменяли пароль администратора.

## 2. Nginx

Пример конфига лежит в `deploy/nginx/parser.conf.example`. Замените `example.com`, скопируйте файл в `/etc/nginx/sites-available/`, включите сайт и добавьте HTTPS через certbot или другой механизм, который вы используете на сервере.

Для `/progress` отключено буферизование, иначе прогресс сканов может обновляться рывками.

## 3. Сохранение текущей базы

Если нужно перенести текущие проекты, бренды, доноры и настройки:

```bash
# на старом проекте остановить приложение и скопировать
cp data/app.db /opt/excel-parser/data/app.db
```

WAL-файлы (`app.db-wal`, `app.db-shm`) переносить не нужно, если приложение остановлено корректно. Если приложение работало во время копирования, сначала сделайте backup через SQLite backup API или остановите контейнер.

## 4. Backup

```bash
./scripts/backup.sh
```

Файл появится в `backups/app_YYYYMMDD_HHMMSS.db`.

## 5. Обновление релиза

```bash
./scripts/backup.sh
docker compose build
docker compose up -d
docker compose logs -f parser
```

## 6. Опциональные парсеры

В основной Docker-образ не ставятся тяжелые дополнительные движки (`crawl4ai`, `scrapy`, `crawlee`, `scrapegraphai`). Базовые методы `requests`, `botasaurus-request`, `botasaurus-browser`, `playwright` остаются доступными.

Если реально нужны все экспериментальные методы подключения, соберите образ так:

```bash
docker compose build --build-arg INSTALL_OPTIONAL_PARSERS=1
docker compose up -d
```

## 7. Проверка

```bash
curl -fsS http://127.0.0.1:5000/api/health
```

Ожидаемый ответ:

```json
{"ok":true}
```
