# ASK-3 — Artisan Plus / cloud / sync / network

**Объект:** `src/plus/`, связка с `artisanlib.main`, `canvas`, `roast_properties`  
**Дата:** 2026-03-20  
**Правила:** выводы с привязкой к модулям/функциям.

---

## Executive summary

Облачный контур **Artisan Plus** изолирован в пакете **`src/plus`**. **Авторизация:** `POST` на `config.auth_url` с email/password → bearer token в `config.token`, повтор при `401` в `connection.sendData`/`getData`. **Клиент:** `plus.connection` (`requests`, gzip, timeouts, `Idempotency-Key` на POST). **Исходящая синхронизация роста:** очередь `persistqueue.SQLiteQueue` в `plus.queue` → POST на `config.roast_url`. **Входящие обновления полей sync-record:** `GET {roast_url}/{uuid}?modified_at=...` в `plus.sync.fetchServerUpdate` → `applyServerUpdates`. Локальные кэши: shelve+lock для sync (`sync.py`), uuid→path (`register.py`), account id→nr (`account.py`), JSON stock (`stock.py`). Граница с локальными данными: поля `roastUUID`, `schedule*`, `plus_*`, `plus_sync_record_hash` в профиле (`main.getProfile` / `setProfile`, `canvas.qmc`).

---

## Cloud integration map

| Компонент | Файл | Назначение |
|-----------|------|------------|
| Конфиг URL, таймауты, имена кэшей | `plus/config.py` | `api_base_url`, `auth_url`, `stock_url`, `roast_url`, `lock_schedule_url`, `notifications_url`, `compress_posts`, TTL кэшей, `queue_*` |
| HTTP + auth + gzip | `plus/connection.py` | `authentify`, `getToken`/`setToken`, `getHeaders`, `sendData`, `getData`, retry на 401 |
| Connect/disconnect, очередь, sync hash при save | `plus/controller.py` | `connect`, `disconnect`, `is_synced`, `updateSyncRecordHashAndSync`, `start` |
| Roast DTO для API | `plus/roast.py` | `getRoast`, `getTemplate`, `getSyncRecord`, списки suppress-атрибутов |
| Pull/push sync-record | `plus/sync.py` | `sync`, `fetchServerUpdate`, `getUpdate`, `applyServerUpdates`, `addSync`/`getSync`, diff/hash |
| Outbox | `plus/queue.py` | `Worker.task`, `addRoast`, `sendLockSchedule`, `is_full_roast_record` |
| Stock/schedule | `plus/stock.py` | `fetch` → `GET stock_url`, кэш, типы Coffee/Blend/ScheduledItem |
| Расписание UI + completed | `plus/schedule.py` | `register_roast`, `register_remaining_item`, completed cache; часть запросов напрямую `connection.sendData` |
| Уведомления | `plus/notifications.py` | `GET notifications_url` |
| Логин UI | `plus/login.py` | диалог email/password, keyring в `controller.connect` |
| Утилиты ссылок/лимитов | `plus/util.py` | `extractAccountState`, `plusLink`, `roastLink`, конверсии температур для payload |

---

## Auth and session handling

- **Запрос:** `connection.authentify()` — body `{'email', 'password'}` на `config.auth_url`, без Bearer (`authorized=False` для этого вызова).
- **Успех:** из JSON `result.user.token` → `setToken`; account `_id` → `account.setAccount` → `config.account_nr`; лимиты/подписка через сигналы `ApplicationWindow`.
- **Хранение:** пароль — keyring (`config.app_name`); токен/nickname — в памяти под `QSemaphore` (`token_semaphore`).
- **Сессия в запросах:** `Authorization: Bearer {token}`; при **401** — `authentify()` и повтор запроса.

Якоря: `connection.authentify` ```150:182:src/plus/connection.py```; retry ```401:427:src/plus/connection.py```.

---

## Data serialization for cloud

- **Полный roast:** `roast.getRoast()` — из `aw.getProfile()` через `getTemplate`, маппинг `id`→`roast_id`, `start_weight`→`amount`, плюс `location`/`coffee`/`blend` из `qmc.plus_*`, опционально `template` из background.
- **Sync record:** `roast.getSyncRecord()` — подмножество ключей `sync_record_attributes`, SHA256 хеш для детекта изменений.
- **Подавление нулей/дефолтов:** `sync.suppress_zero_values` / списки в `roast.py` (`sync_record_zero_supressed_*`, `fifty`, empty string) — экономия трафика и семантика null на сервере.
- **Partial upload:** `sync.diffCachedSyncRecord` относительно `cached_sync_record` перед постановкой в очередь.
- **Профиль `.alog`:** `plus_sync_record_hash` пишется при save/autosave из `controller.updateSyncRecordHashAndSync()` — см. `main.fileSave` / `automaticsave`.

---

## API client structure

- Единая обёртка: `sendData(url, data, verb, authorized, compress)` → JSON utf-8 → при размере > threshold gzip + `Content-Encoding: gzip`; POST добавляет `Idempotency-Key`.
- `getData(url, authorized, params)` — GET с теми же headers/session.
- User-Agent: `Artisan/{version} (os; …)` из `aw.get_os()`.

---

## Sync lifecycle

1. **Подключение:** `controller.connect` → `authentify` → `config.connected`, `queue.start()`.
2. **После load профиля:** при `plus_account` и `roastUUID` в объекте — `QTimer.singleShot(100, plus.sync.sync)` (`main.loadFile`).
3. **`sync.sync()`:** сверка `plus_sync_record_hash` с текущим `getSyncRecord`; `getUpdate(roastUUID, curFile)` → `fetchServerUpdate`:
   - **204** — нет более новых данных (или рекурсия для seed sync cache);
   - **200** + `result` — если `modified_at` новее `plus_file_last_modified`, `applyServerUpdates`;
   - **404** + `success:false` — запись удалена на сервере → `delSync(uuid)`.
4. **Push:** при save `updateSyncRecordHashAndSync` → если sync-record изменился и профиль «под sync» — `queue.addRoast(sync_record)`; полный рост — `queue.addRoast()` без аргумента или с полным dict.
5. **Worker:** `queue.py` — только если `is_full_roast_record` или uuid в sync cache; успех → `sync.addSync(roast_id, modified_at)`; при конфликте **409** — задача сбрасывается.

---

## Reuse constraints and risks

| Риск | Комментарий |
|------|-------------|
| GPL | Модули `plus/*` под GPL v2/v3+ — копирование в проприетарный продукт без юр. оценки рискованно |
| API-контракт | Нет OpenAPI в репо; совместимость только по фактическому поведению клиента |
| Связность с Qt | `config.app_window`, сигналы, `QTimer`, `QThread` в queue/stock |
| Кэши shelve + lock | Восстановление после сбоев через удаление lock — операционный риск |
| One-way поля | `sync_record_zero_supressed_attributes_unsynced` в `roast.py` — только в сторону сервера |

---

## Таблица (обязательная)

| Компонент | Где | Что делает | UI | Переиспользовать идею | Действие |
|-----------|-----|------------|-----|------------------------|----------|
| connection | `plus/connection.py` | Auth, GET/POST/PUT | Косвенно | Да | Исследовать / адаптировать |
| controller | `plus/controller.py` | ON/OFF, credentials | Да (иконка, сообщения) | Частично | Переписать слой состояния |
| queue | `plus/queue.py` | Outbox, retry | Сообщения | Да | Сохранить паттерн |
| sync | `plus/sync.py` | Pull, apply, cache | Блокировка Roast Properties при pull | Да | Ядро концепции |
| roast | `plus/roast.py` | DTO | Через свойства обжарки | Да | Высокая ценность |
| stock | `plus/stock.py` | Склад/расписание | Roast properties, scheduler | Частично | MVP опционально |
| schedule | `plus/schedule.py` | Scheduler, completed | Окно расписания | Частично | Убрать из узкого MVP или отложить |
| notifications | `plus/notifications.py` | Push в NotificationManager | Да | Низкий приоритет | Не трогать в MVP |

---

## Specific files for next deep-dive

- `plus/schedule.py` (объёмный UI+домен)
- `plus/stock.py` (`getBlends`, кэш invalidation)
- `artisanlib/main.py` — `loadFile`, `fileSave`, `stateChanged` → `plus.sync.getUpdate`
- `artisanlib/roast_properties.py` — вызовы `plus.stock`, `plus.queue.addRoast`

---

*Конец ASK-3.*
