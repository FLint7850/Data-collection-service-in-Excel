# Excel Data Collector UI

Nuxt-интерфейс для существующего Python API.

## Структура

- `app/pages` — маршруты и сборка экранов;
- `app/components` — переиспользуемые блоки интерфейса;
- `app/composables` — общее реактивное состояние и polling;
- `app/services` — типизированные HTTP-операции по предметным областям;
- `app/types` — API-контракты;
- `app/utils` — форматирование и UI-маппинги;
- `server` — Nitro-прокси к Python API.

## Запуск

```powershell
npm ci
npm run dev
```

По умолчанию Nitro ожидает API на `http://127.0.0.1:5055`.
Адрес можно изменить через `NUXT_BACKEND_URL`.

## Проверка

```powershell
npm run typecheck
npm run build
```
