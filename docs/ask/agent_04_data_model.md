# ASK-4 — Data model / persistence / import-export / settings

**Объект:** Artisan / Roaster Scope (`src/artisanlib`, `src/plus`)  
**Дата:** 2026-03-20  

---

## Executive summary

Доменная «сущность файла» — **`ProfileData` (TypedDict)** в `atypes.py`: один словарь объединяет ряды **`timex` / `temp1` / `temp2`**, индексы фаз **`timeindex`**, события **`specialevents*`**, метаданные партии, настройки отображения, alarms, energy, plus-поля и т.д. Снимок для файла строится **`ApplicationWindow.getProfile`** и загружается **`setProfile`** (`main.py`). Нативный **`.alog`**: **`util.serialize`** пишет `repr(dict)`, **`deserialize`** читает через **`ast.literal_eval`** — ```973:989:src/artisanlib/util.py```. Настройки приложения — **`QSettings`** + экспорт **`.aset`** / темы **`.athm`** (см. `saveAllSettings`, `settingsLoad`, `closeEventSettings_theme` в `main.py`). CSV — **`csv_load` / `exportProfile2CSV`** (`util.py`, `main.py`); покрытие CSV **не полный** профиль (sanity: `src/test/sanity/test_load_save.py`). Plus: проекция **`getRoast`** / sync record в `plus/roast.py`, реестр UUID→path — **shelve** в `plus/register.py`.

---

## Scope

Roast/profile/session структуры, config, alarms/events, форматы, граница model vs serialization, слабые места, нормализация для нового приложения.

---

## Data entity table

| Data entity | Где найдена | Назначение | Текущие проблемы | Сохранить концептуально | Перепроектировать |
|-------------|-------------|------------|------------------|-------------------------|-------------------|
| **`ProfileData`** | `artisanlib/atypes.py` (`class ProfileData`) | Единый контейнер файла профиля | Монолит; много optional ключей; эволюция без явной схемы | Один «снимок сессии» для обмена | Версионирование, разбиение на под-документы |
| Ряды ET/BT + время | ключи `timex`, `temp1`, `temp2` в `ProfileData` | Основные кривые | Смешение с вычисляемыми/legacy полями | Семантика двух основных рядов + extras | Явная модель `Series` + sample rate metadata |
| Фазы / маркеры | `timeindex`, вычисляемое `ComputedProfileInformation` | Таймлайн обжарки | Индексы vs времена рассинхрон при правках | Фазы как события | Нормализованные `RoastEvent` |
| Пользовательские события | `specialevents*`, `etypes` | Аннотации | Параллельные списки по индексу | События на временной шкале | Одна таблица событий |
| Alarms | поля в профиле + `alarms.py`, `.alrm` | Автоматизация | Дублирование с UI state | Rule-based alarms | Модель правил и триггеров |
| Palettes / кнопки | `Palette` в `atypes.py`, `events.py` | UX конфиг | Связь с индексами слотов | Пресеты оператора | Отдельный конфиг слоя представления |
| **Нативный `.alog`** | `util.serialize`/`deserialize` | Legacy native | `literal_eval`, без строгой схемы | Только импорт legacy | Новый формат (JSON/MessagePack + schema) |
| **JSON/CSV** | `exportJSON`/`importJSON`, `csv_load` | Обмен | CSV — подмножество | Каналы интеграции | Контракты и тесты покрытия |
| **QSettings + `.aset`** | `main.py` | Глобальные настройки | INI/Qt-специфика | Разделение профиль vs app config | Явная схема настроек |
| Plus sync | `plus_sync_record_hash` и др. в профиле, `plus/roast.py` | Облако | Зависимость от внешнего API | Hash/sync идея | Свой backend или контракт |

---

## Roast/session data structures

- **`ProfileData`** начинается с версий записи и ОС, далее метаданные, ряды, события — ```128:207:src/artisanlib/atypes.py``` (фрагмент; поле `temp2` и далее продолжается в файле).
- **`getProfile` / `setProfile`** — центральная логика кодирования строк, единиц, миграций при загрузке: `main.py` ```15721:```, ```17013:```.
- **Временное хранение во время сессии:** массивы на `tgraphcanvas` (`timex`, `temp1`, …) в `canvas.py`; персистентность — через snapshot в `getProfile` (см. ASK-1 границу runtime vs saved).

---

## Config and settings model

- Экземпляр приложения использует **`QSettings`** (организация/имя заданы в коде `main.py` / util).
- Экспорт «всех настроек» в **`.aset`** и загрузка — для переноса машин между установками (см. меню Config / Machine).
- Темы: **`.athm`** через сохранение темы при закрытии ( `closeEventSettings_theme` ).

---

## Import/export and serialization

| Формат | Запись | Чтение | Примечание |
|--------|--------|--------|------------|
| `.alog` | `util.serialize` → `repr` | `util.deserialize` → `ast.literal_eval` | Нативный legacy |
| JSON | `exportJSON` / `importJSON` | парсинг в `setProfile`-подобный путь | Зависит от ключей `ProfileData` |
| CSV | `exportProfile2CSV` | `csv_load` в `util.py` | Подмножество полей |
| Alarms file | из `alarms.py` | `loadAlarmsFromProfile` в `main.py` | JSON `.alrm` |

**Граница model vs serialization:** формально `getProfile` строит dict, `serialize` пишет файл; фактически **миграции и бизнес-правила вмонтированы в `setProfile`**, отдельного слоя схемы нет.

---

## Weak points in current data architecture

1. **Монолитный `ProfileData`** — слабая нормализация; ключи растут между версиями Artisan.
2. **`.alog` через literal_eval** — риск безопасности и хрупкость при смене Python/представлений.
3. **Параллельные списки** для specialevents (тип/значение/строка) — легко рассинхронизировать.
4. **CSV не эквивалентен профилю** — ловушки для интеграторов без чтения тестов.

---

## Proposed normalized entity set (новое приложение)

1. **`RoastSession`** — id, operator, batch, machine ref, время, метаданные зёрен.
2. **`MeasurementSeries`** — канал (ET/BT/extra), единицы, массив (t, v) или колоночный формат.
3. **`RoastEvent`** — type, t, value, label, source (user/auto).
4. **`AlarmRuleSet`** — отдельно от сырых рядов.
5. **`AppSettings`** / **`MachinePreset`** — не смешивать с session snapshot.
6. **`ExternalSyncState`** — опционально, если нужен cloud.

---

## Key files

- `src/artisanlib/atypes.py` — `ProfileData`, `ComputedProfileInformation`, типы alarms/palette.
- `src/artisanlib/main.py` — `getProfile`, `setProfile`, settings, import/export wiring.
- `src/artisanlib/util.py` — `serialize`, `deserialize`, `csv_load`.
- `src/artisanlib/alarms.py` — персистентность alarms.
- `src/plus/roast.py`, `src/plus/register.py` — plus DTO и реестры.

---

## Confirmed conclusions

- Центр модели — **`ProfileData` + get/setProfile + util.serialize**, не один вспомогательный модуль вроде `roast_properties.py` (см. противоречие C1 в master-report).

---

## Uncertain / requires deeper check

- Полный список ключей JSON vs CSV (лучше выгрузить из тестов и `getProfile`).
- Все пути **autosave** и их влияние на plus hash.

---

## Reuse / redesign / rewrite

- **Reuse:** идея «один файл — полная сессия»; раздельные артефакты настроек и профиля.
- **Redesign:** версионированная схема и миграции вне `setProfile`.
- **Rewrite:** native `.alog` как основной формат нового продукта.

---

## Open questions

- Требуется ли бинарный или колоночный формат для длинных рядов?
- Нужна ли совместимость импорта **100%** полей Artisan в v1?
