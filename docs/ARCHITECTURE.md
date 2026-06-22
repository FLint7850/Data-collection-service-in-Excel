# Архитектура проекта

## Точки входа

- `app.py` — совместимый локальный запуск, используется текущими `.cmd`/`.ps1` файлами.
- `run_production.py` — production-запуск через Waitress.
- `wsgi.py` — WSGI-объект `app` для внешнего сервера.
- `parser_app/server.py` — локальный threaded WSGI-сервер.

## Backend

```text
parser_app/
├── runtime.py              конфигурация, Flask, блокировки и разделяемое состояние
├── bootstrap.py            загрузка модулей в безопасном порядке
├── server.py               локальный WSGI-сервер
├── routes/
│   ├── core.py             авторизация, главная страница, общие API
│   ├── projects.py         API проектов
│   ├── news.py             API мониторинга новинок
│   ├── file_import.py      API импорта файлов
│   └── legacy.py           совместимые старые endpoints и SSE progress
└── services/
    ├── lifecycle.py        lifecycle Flask и DB session на запрос
    ├── common.py           общие DTO, нормализация настроек, init storage
    ├── projects.py         проекты и их runtime-state
    ├── logging_service.py  единый журнал и автоочистка
    ├── news_settings.py    бренды, доноры, настройки мониторинга
    ├── normalization.py    URL, строки и выделение модели
    ├── extraction.py       HTML/JSON-LD extraction и правила замены
    ├── fetching.py         requests/browser/parser engines
    ├── crawler.py          многопоточный обход сайта
    ├── file_import.py      XLSX/CSV import и сравнение
    ├── feeds.py            загрузка и разбор XML-фидов
    ├── news_scan.py        сканирование, enrichment, CSV и почта
    └── scheduling.py       расписание и фоновый scheduler
```

`runtime.py` хранит только действительно общие объекты: Flask application, immutable-конфигурацию, locks, events и словари текущего состояния. Бизнес-функции находятся в соответствующих сервисах.

`bootstrap.py` является слоем совместимости для существующей логики, которая исторически использовала общие module globals. Он связывает сервисы один раз при старте. Это позволяет сохранить поведение долгих потоковых операций и постепенно переводить отдельные сервисы на явную dependency injection без возврата к монолитному `app.py`.

## Frontend

```text
static/js/app/
├── core.js        DOM, общее состояние, HTTP helper, UI проектов
├── settings.js    настройки, собственные сайты, фиды, импорт
├── news.js        карточки брендов и модальное окно мониторинга
├── workspace.js   загрузка данных, общий render и логи
└── events.js      обработчики действий и EventSource progress
```

Файлы подключаются в указанном порядке в `templates/index.html`. Порядок важен, поскольку текущий UI сохраняет общий runtime-state без framework и сборщика.

## Инициализация

`ensure_storage()` теперь idempotent: миграции, загрузка проектов и настроек, а также запуск scheduler выполняются один раз на процесс. Повторные обращения API больше не перечитывают всю БД.

Для тестового принудительного перечитывания существует `ensure_storage(force_reload=True)`.

## Ограничение по процессам

Crawler, события остановки, прогресс и scheduler хранятся в памяти процесса. Поэтому production должен запускаться **одним процессом с несколькими потоками**. Нельзя запускать несколько Gunicorn workers без отдельного переноса state/queue в Redis или другую внешнюю систему.
