# Архитектура проекта

## Стек

- Backend: Flask 3, SQLAlchemy 2, SQLite, Alembic.
- Frontend: обычные шаблоны Jinja + `static/js/app.js` + `static/css/styles.css`.
- Сбор данных: `requests`, Botasaurus/Playwright, опционально `crawl4ai`, `scrapy`, `crawlee`, `scrapegraphai`.
- Runtime: фоновые потоки Python, in-memory состояние сканов, SQLite WAL.

## Почему один процесс

Состояние активных сканов хранится в глобальных структурах Python: `projects`, `news_settings`, `news_scan_threads`, `news_stop_events`, `active_crawler`. Поэтому приложение запускается в production как один Gunicorn worker с несколькими thread. Несколько worker-процессов создадут несколько независимых планировщиков и разное состояние UI.

## Основные таблицы

### users

Пользователи для входа в интерфейс: `username`, `password_hash`, `is_active`, timestamps. Индексы: `username` unique + `ix_users_username`.

### projects

Проекты полного сканирования: стартовые URL, потоки, исключения, фильтры товарных URL, правила извлечения, runtime-state, метод подключения и автопереключение.

### brands

Группы/бренды для новинок: название, группа, состояние скана, расписание, активность, основной донор.

### donors

Сайты-доноры брендов: URL, стартовые URL, потоки, метод подключения, исключения, фильтры, правила извлечения, настройки селекторов, уже виденные модели.

### own_sites

Собственные XML-фиды для сравнения новинок.

### app_settings

Глобальные настройки: автоочистка логов, SMTP, локальное хранилище фидов.

### file_import

Настройки и состояние импорта Excel/CSV: исключения, поле модели, правила замены, исходный файл, результат сравнения.

### connection_methods

Справочник методов подключения. Флаги `is_browser_render` и `is_debug_visible` нужны для ограничения браузерных методов и скрытия диагностических режимов из fallback.

## Runtime-папки

Эти папки не должны храниться в git и должны монтироваться как volume/обычные директории на сервере:

- `data/` — SQLite база.
- `logs/` — runtime-логи.
- `exports/` — CSV-выгрузки.
- `feeds/` — скачанные XML-фиды и snapshots.
- `storage/` — импортированные файлы и браузерные runtime-данные.
- `backups/` — backup SQLite.

## Безопасность

- `.env` не входит в поставку.
- В production запрещены дефолтные `FLASK_SECRET_KEY` и `AUTH_DEFAULT_PASSWORD=admin`.
- Cookie: `HttpOnly`, `SameSite`, `Secure` при production.
- За Nginx включается `ProxyFix` через `TRUST_PROXY_HEADERS=1`.
- Логин ограничен по количеству неудачных попыток.
- Скачивание экспортов ограничено директорией `exports`.
- Контейнер запускается не от root-пользователя.
