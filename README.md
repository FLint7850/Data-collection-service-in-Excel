# Сервис сбора данных в Excel

Flask-сервис для обхода каталогов, извлечения моделей и цен, сравнения с XML-фидами, мониторинга новинок и выгрузки CSV.

## Локальный запуск Windows

Дважды нажмите:

```text
START_PARSER.cmd
```

Скрипт создаст `.venv`, установит зависимости, подготовит Chromium и откроет приложение. Порт берётся из `.env`; локальный скрипт при занятом `5055` попробует следующий свободный порт.

Ручной запуск:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

## Production

```bash
python -m venv .venv
python -m pip install -r requirements.txt
# Для всех дополнительных движков: python -m pip install -r requirements-all.txt
python -m playwright install chromium
python run_production.py
```

Перед запуском скопируйте `.env.example` в `.env` и задайте безопасные `FLASK_SECRET_KEY`, логин и пароль первого пользователя.

Полная инструкция: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Структура

Монолитные `app.py` и `static/js/app.js` разделены по областям ответственности:

- `parser_app/services/` — бизнес-логика;
- `parser_app/routes/` — HTTP API;
- `parser_app/runtime.py` — конфигурация и разделяемое состояние;
- `static/js/app/` — frontend по функциональным модулям;
- `tests/` — smoke, initialization, normalization и production checks.

Подробно: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Проверки перед коммитом

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
ruff check app.py wsgi.py run_production.py parser_app db.py models.py alembic tests
```

## Дополнительные движки

`requirements.txt` содержит основной production-набор. Тяжёлые дополнительные движки вынесены в `requirements_optional_parsers.txt`; полный набор устанавливается через `requirements-all.txt`. Локальные Windows-скрипты используют полный набор и сохраняют прежнее поведение.

## Публичная ссылка через xTunnel

Используйте:

```text
START_PUBLIC_PARSER.cmd
```

Перед первым запуском выполните `INSTALL_XTUNNEL.cmd` и активируйте xTunnel. Публичный туннель предназначен для временного доступа, а не для постоянного production-развёртывания.

## Дополнительные документы

- `REFACTOR_REPORT.md` — полный отчёт о рефакторинге и выполненных проверках.
- `docs/ARCHITECTURE.md` — устройство проекта.
- `docs/DEPLOYMENT.md` — production-развёртывание.
