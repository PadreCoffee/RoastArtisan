# ASK-6 — Architecture / coupling / extraction feasibility / technical debt

**Объект:** Artisan / Roaster Scope (репозиторий RoastArtisan)  
**Дата:** 2026-03-20  

---

## Executive summary

Архитектура — **классический PyQt desktop-монолит**: **`ApplicationWindow`** (`main.py`) — центр гравитации (UI, конфиг, устройства, файлы, Plus, часть бизнес-правил). **График и сэмплинг** — **`tgraphcanvas` + `SampleThread`** (`canvas.py`), плотно связанные с Qt сигналами и семафорами. **Данные сессии** — параллельно в виде **runtime-буферов** на `qmc` и **сериализуемого `ProfileData`** (`getProfile`/`setProfile`). **Device layer** — **`comm.py`** + разнесённые транспорты (`modbusport.py`, …). **Plus** — относительно отдельный пакет `src/plus`, но интеграция идёт через то же окно. Для нового продукта: **извлекаемы идеи и узкие модули** (typed dict контракты, modbus client shape, outbox sync), **переписать** — центральное окно, comm-реестр драйверов, `sample_processing` без Qt.

---

## Scope

Границы модулей, coupling, global state, god objects, что extract vs rewrite, риски, приоритет углублений.

---

## Architecture map

```
ApplicationWindow (main.py) — UI, настройки, устройства, Plus
        ├─► tgraphcanvas + SampleThread (canvas.py) — сэмплинг, график
        ├─► getProfile/setProfile + util — персистентность
        └─► comm.serialport + modbusport / S7 / ws — device layer
ProfileData (atypes.py) — контракт «снимка» файла профиля
plus/* — облако (относительно отдельный пакет, интеграция через main)
```

- **Явных микросервисов / слоёв** нет: граница «пакет `plus`» и «файлы протоколов» — лучшие естественные швы.

---

## Coupling analysis

| Между | Как проявляется | Сила |
|-------|------------------|------|
| UI ↔ sampler | `sample_processingSignal` → слот на `qmc`; семафоры в том же классе | Очень высокая |
| UI ↔ devices | `aw.ser`, `aw.modbus`, … созданы в окне; sample читает через `aw` | Очень высокая |
| UI ↔ persistence | `fileSave`, `loadFile`, `getProfile` на `ApplicationWindow` | Очень высокая |
| metrics ↔ UI | RoR и автособытия внутри `sample_processing` | Высокая |
| plus ↔ core | вызовы sync после load/save; хэши в профиле | Средняя |
| typed dict ↔ legacy files | ключи `ProfileData` разрастаются | Средняя–высокая |

**Global state:** доменная сессия и устройства держатся на **одном долгоживущем окне**; множество флагов (`flagon`, `flagstart`, …) на `qmc`.

**God object:** `ApplicationWindow` и частично `tgraphcanvas` (размер и ответственность).

**Implicit contracts:** индексы `device`/`extradevices`; параллельные списки событий; literal `.alog`.

---

## Подсистема → рекомендация

| Подсистема | Состояние архитектуры | Связанность | Риск reuse | Рекомендация |
|------------|------------------------|-------------|------------|--------------|
| `main.py` ApplicationWindow | Монолит | Очень высокая | Высокий при копировании | **Rewrite** как composition root; не **Extract** целиком |
| `canvas.py` sampling+plot | Смешение | Очень высокая | Средний | **Redesign**: отдельный sampler + отдельный plot adapter |
| `comm.py` drivers | Рабочий, огромный | Высокая к окну | Высокий | **Rewrite** целевой набор; **Extract** единичные драйверы с аудитом GPL |
| `modbusport` / network clients | Относительно модульные | Средняя | Средний | **Extract** идеи; код — осторожно |
| `atypes.ProfileData` | Ясный typed surface | Средняя (к файлам) | Низкий для копирования dict | **Redesign** доменной модели; **не** тащить как единственную схему |
| `util.serialize` `.alog` | Простой, хрупкий | Низкий к остальному | Высокий при использовании как native | **Defer** / только legacy import |
| `plus/*` | Модульный пакет | Средняя к API | Лицензия + нестабильный внешний контракт | **Extract concept** (outbox, sync); **Rewrite** интеграцию |
| `uic` + dialogs | Разбросано | Средняя | Низкий | **Rewrite** UI |

---

## Reusable extraction candidates (концептуально)

- **Outbox + pull sync по `modified_at` + hash записи** — см. `plus/queue.py`, `plus/sync.py` (детали в ASK-3 файле).
- **Block-oriented industrial reads** (Modbus/S7) — паттерн кэша регистров.
- **Разделение файла профиля и файла настроек** — `.alog` vs `.aset`.
- **Typed snapshot** — идея `ProfileData` как контракта обмена (не как внутренняя БД).

---

## Rewrite candidates

- Центральное **окно** и меню как единый класс.
- **`devicefunctionlist` по индексам** → registry сервис.
- **`sample_processing`** как чистая доменная цепочка без прямого matplotlib update в том же методе (разделить на compute + present).

---

## Technical risks

1. **Недооценка миграции `ProfileData`** — скрытые ключи и legacy файлы.
2. **Копирование `comm.py`** — GPL, объём, неявные зависимости от `qmc`.
3. **Параллельная работа UI-thread и sampler** — семафоры маскируют гонки; новый дизайн должен явно моделировать backpressure.
4. **Plus API** — внешняя нестабильность; юридические ограничения при форке.
5. **literal_eval** на пользовательских файлах — безопасность и совместимость.

---

## Mature ideas worth keeping

- Сигнал **«снимок профиля»** как единый артефакт обжарки.
- Вынос **сетевых транспортов** в отдельные классы.
- **Simulator** для UX-тестов без железа.
- **Тесты sanity** на load/save (`src/test/sanity/test_load_save.py`) как ориентир контрактов CSV/JSON.

---

## Priority list for deeper investigation

1. **Полный grep `ADD DEVICE:`** и оценка стоимости нового драйвера.
2. **Инвентаризация `plus/schedule.py`** (если cloud в scope).
3. **Race conditions**: все использования `profileDataSemaphore` / `samplingSemaphore`.
4. **Лицензионный аудит** зависимостей для форка.

---

## Confirmed conclusions

- Центральная связность сосредоточена в **`ApplicationWindow` + `tgraphcanvas`**; plus-пакет границу держит лучше, чем artisanlib average.

---

## Uncertain / requires deeper check

- Использование **multiprocessing** / внешних процессов (если есть) для долгих задач.
- Полная карта **циклических импортов** между artisanlib модулями.

---

## Open questions

- Целевой объём паритета с Artisan devices в новом продукте?
- Headless core: допустим ли **без Qt** для embedded?
