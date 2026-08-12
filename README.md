# Data-collection-service-in-Excel

Сервис сбора данных в Excel: https://github.com/FLint7850/Data-collection-service-in-Excel

Сервис для обхода каталогов, сбора моделей и цен, управления исключениями и выгрузки CSV.

Интерфейс полностью перенесён на Nuxt 4, Nuxt UI, TypeScript, Nitro и Tailwind CSS.
Python/Flask отвечает только за API, фоновые задания и хранение данных.

## Запуск в Docker

```powershell
docker compose up -d --build
```

После запуска откройте `http://127.0.0.1/`. В Docker наружу публикуется только
Nginx с Nuxt-интерфейсом; Flask API доступен только внутри Docker-сети.

### Прокси для внешних источников

Парсеры, фиды и Codex используют один явный HTTP(S)-прокси только для внешних
адресов. Внутренние обращения между Flask, Nuxt, Nginx, localhost и приватными
сетями идут напрямую. Настройка хранится только в локальном `.env`:

```dotenv
OUTBOUND_PROXY_URL=http://LOGIN:PASSWORD@PROXY_HOST:PROXY_PORT
OUTBOUND_PROXY_REQUIRED=1
OUTBOUND_PROXY_NO_PROXY=localhost,127.0.0.1,::1,parser,frontend,nginx,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

Если в логине или пароле есть специальные символы, их нужно URL-кодировать.
При `OUTBOUND_PROXY_REQUIRED=1` внешние запросы не переключаются молча на
настоящий IP, когда адрес прокси отсутствует или некорректен. После изменения
`.env` пересоздайте контейнер `parser`.

## Быстрый запуск в PowerShell

Самый простой вариант: дважды нажмите файл:

```text
START_PARSER.cmd
```

Он сам перейдет в папку проекта, подготовит Python и Node.js-зависимости, запустит API и Nuxt-интерфейс, затем откроет `http://127.0.0.1:3000`.

Для запуска нужны Python 3.10+ и Node.js 20+.

## Публичная ссылка через xTunnel

Для доступа с других компьютеров используйте:

```text
START_PUBLIC_PARSER.cmd
```

Перед первым запуском нужно один раз установить и активировать xTunnel.

Самый простой способ для этого проекта:

```text
INSTALL_XTUNNEL.cmd
```

Он скачает официальный Windows x64 архив xTunnel в папку проекта и предложит вставить ключ активации.

Альтернативный способ установки в Windows через Chocolatey:

```powershell
choco source add -n=xtunnel -s="https://www.myget.org/F/xtunnel/api/v2"
choco install xtunnel
xtunnel register YOUR_KEY
```

После запуска `START_PUBLIC_PARSER.cmd` скопируйте публичную HTTPS-ссылку из окна xTunnel и отправьте ее другим пользователям. Окно нельзя закрывать, пока ссылка нужна.

Для текущей активации публичный запуск использует:

```powershell
xtunnel http PORT --tunnel-host tunnel4.com
```

Если установлен Python 3.10+, выполните из папки проекта:

```powershell
.\run.ps1
```

Если PowerShell блокирует запуск скриптов:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

После запуска откройте:

```text
http://127.0.0.1:3000
```

## Ручной запуск

Команда `pip` может отсутствовать в PATH. Надежнее запускать pip через Python:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Во втором окне PowerShell запустите frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Nuxt будет доступен на `http://127.0.0.1:3000`, а Nitro автоматически проксирует API в Python-сервис.
При таком ручном запуске Python API работает на `http://127.0.0.1:5000`.
Nuxt читает адрес API из корневого `.env`, поэтому отдельный `frontend/.env` не нужен.

Если команда `python` тоже не найдена, установите Python 3.10+ с https://www.python.org/downloads/ и отметьте пункт `Add python.exe to PATH` при установке.

## Если сайт отдает пустую страницу или блокировку

В проект подключен fallback через Botasaurus. Обычный `requests` используется первым, а при подозрении на блокировку или пустой JS-шаблон приложение пробует:

1. `botasaurus.request` для браузероподобного HTTP-запроса.
2. `botasaurus.browser` для headless-рендеринга страницы.

После обновления зависимостей просто перезапустите:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

## Скорость сбора

В каждом проекте есть поле `Потоки`. Рекомендуемые значения:

- `3-4` для спокойной проверки одной категории.
- `6-8` для ускоренного сбора, если сайт отвечает стабильно.
- `10-16` только если нет ошибок, зависаний и блокировок.

Кнопка `Приостановить с результатом` останавливает текущий сбор и формирует CSV из уже найденных товаров.

## Проекты и несколько ссылок

В интерфейсе можно создать несколько вкладок-проектов. Каждый проект хранит:

- название;
- список стартовых URL, по одному на строку;
- исключения;
- количество потоков;
- собственный прогресс;
- последний CSV-файл;
- собственные логи.

Проекты можно запускать параллельно. Для просмотра всех событий откройте вкладку `Логи`. Там же можно включить автоочистку логов старше 7 суток или очистить логи вручную.
