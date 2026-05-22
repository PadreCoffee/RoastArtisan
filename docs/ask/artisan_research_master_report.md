# Artisan / Roaster Scope — master research report

**Дата сборки:** 2026-03-20  
**Промпты:** `assemble_reports_prompt.md`, шаблон `ask_prompts/07_report_template.md`  
**Входные ASK:** [`agent_01`](./agent_01_core_logging.md) … [`agent_06`](./agent_06_architecture_risks.md) — см. [индекс](#индекс-ask-артефактов).

---

## Executive summary

- **Сессия обжарки** живёт в **`tgraphcanvas`** (`canvas.py`): **`flagon`** = мониторинг/опрос, **`flagstart`** = запись в буферы профиля. **`SampleThread`** снимает main+extra через **`devicefunctionlist`**, результат уходит в **`sample_processing()`** (GUI thread): фильтры, **RoR**, автособытия, **`updategraphics`**. Входы с панели — **`ApplicationWindow`** (`main.py`). *ASK-1.*

- **Оборудование** — не интерфейс `Device`, а **индекс → callable** в **`comm.serialport.devicefunctionlist`** + отдельные **`modbus`** / **`s7`** / **`ws`** на окне. Запись в железо разрозненная (часть через `main.eventaction*`). *ASK-2.*

- **Artisan Plus** изолирован в **`src/plus`**: auth (`connection`), outbox (`queue`), pull по **`modified_at`** + hash (`sync`), DTO из **`getProfile`** (`roast.py`). Интеграция через то же окно и поля профиля (`plus_sync_record_hash`, …). *ASK-3.*

- **Данные файла** — монолитный **`ProfileData`** (`atypes.py`), снимок **`getProfile` / `setProfile`** (`main.py`), нативный **`.alog`** = **`repr` + `ast.literal_eval`** (`util.py`). Настройки — **QSettings** / **`.aset`**. CSV/JSON — неполный паритет с профилем. *ASK-4.*

- **UI** — одно **`ApplicationWindow`**, меню File/Roast/Config/… в коде, график matplotlib внутри окна; сильная сращенность с доменом и устройствами. *ASK-5.*

- **Архитектура** — PyQt-монолит: god-window + **`qmc`** + параллельно runtime-буферы и сериализуемый snapshot. Для нового продукта: **переносить идеи** (sampler→processor, промышленные клиенты, outbox+sync, раздельно профиль/настройки), **не тащить как есть** comm-реестр, literal **`.alog`**, полный **`setProfile`**, копию **Plus** без GPL/API-оценки. *ASK-6.*

---

## Scope

Синтез шести ASK-исследований по текущему коду `RoastArtisan` (`src/artisanlib`, `src/plus`): logging pipeline, device layer, cloud, persistence/UI model, экраны/воркфлоу, связность и извлекаемость.  
**Вне scope:** продуктовый бриф, дорожная карта, правки коду.

---

## Findings (единая картина по блокам)

### 1. Core logging / roast session pipeline (ASK-1)

| Элемент | Суть |
|---------|------|
| Включение опроса | `OnMonitor`: `flagon`, `createSampleThread()` |
| Запись | `OnRecorder`: `flagstart`, `resetTimer`, выравнивание осей |
| Поток | `SampleThread.run` → `sample()` → `sample_processingSignal` |
| Метрики | `compute_ror` / polyfit, delta ET/BT в `sample_processing` |
| Фазы | `timeindex`, `markCharge`…`markDrop`, auto-события в том же процессоре |
| График | `updategraphics` после сэмпла, `redraw` для полного пересчёта |

Идея для выноса: **state machine** (monitor/recording) + **scheduler** + **acquisition** + **один процессор рядов/событий** + отдельный **observer** для UI/файла.

### 2. Device layer / protocol integration (ASK-2)

- Опрос: `sample_main_device` / `sample_extra_device` → **`devicefunctionlist[device]`**.
- Транспорты: serial-протоколы в **`comm.py`**, Modbus **`modbusport.py`**, S7, WebSocket **`wsport`**, отдельные asyncio-клиенты (Kaleido, Santoker, …).
- Новое железо: тег **`ADD DEVICE:`** в нескольких файлах (`comm.py`, `devices.py`, `canvas.py`).

### 3. Artisan Plus / cloud / sync (ASK-3)

- HTTP: gzip, `Idempotency-Key`, retry на **401**.
- Push: SQLite queue → POST roast URL.
- Pull: GET с `modified_at`, применение **`applyServerUpdates`**.
- Риски: **GPL**, нет OpenAPI, связность с Qt (`QTimer`, сигналы).

### 4. Data model / persistence / import-export (ASK-4)

- **`ProfileData`** — один TypedDict на «всё»; эволюция ключей неформализована.
- **`.alog`**: удобство совместимости vs **`literal_eval`** (безопасность/хрупкость).
- Разделить концептуально: **RoastSession**, **MeasurementSeries**, **RoastEvent**, **AppSettings**, **MachinePreset**, **ExternalSyncState**.

### 5. UI / UX / role decomposition (ASK-5)

- Критический поток: Machine preset → **ON** → **START** → фазы → **STOP** → Save/Export.
- Перегруз: **`main.py`**, Config/Machine, Tools/Analyzer для узкого MVP не обязательны.
- Роли: **Novice / Roaster / Engineer** — сокращение поверхности для MVP.

### 6. Architecture / coupling / extraction (ASK-6)

- Сильнейшие швы: пакет **`plus/`**, модули **`modbusport`** и аналоги.
- Слабейшие: **`ApplicationWindow`**, **`sample_processing`**, **`comm.py`** целиком.

---

## Key files (сводный указатель)

| Область | Файлы |
|---------|--------|
| Сессия / сэмплинг / график | `artisanlib/canvas.py` |
| Главное окно, меню, get/setProfile | `artisanlib/main.py` |
| Драйверы / `devicefunctionlist` | `artisanlib/comm.py` |
| Modbus | `artisanlib/modbusport.py` |
| S7 / WS | `artisanlib/s7port.py`, `artisanlib/wsport.py` |
| Модель профиля | `artisanlib/atypes.py` |
| Сериализация | `artisanlib/util.py` |
| Plus | `src/plus/*.py` (см. ASK-3) |
| Тесты контрактов load/save | `src/test/sanity/test_load_save.py` (упом. ASK-6) |

---

## Confirmed conclusions (сквозные)

1. Опрос и запись разделены флагами **`flagon`** / **`flagstart`**, реализация сосредоточена в **`canvas.py`**. *(ASK-1)*
2. Чтение датчиков идёт через **`devicefunctionlist`** и индексы **`qmc.device` / `extradevices`**. *(ASK-2)*
3. Plus — отдельный пакет с **outbox + sync по hash/modified_at**; граница с профилем через **`getProfile`** / поля sync. *(ASK-3)*
4. Центр данных файла — **`ProfileData` + `getProfile`/`setProfile`**, не один только редактор свойств. *(ASK-4, ASK-6 — снятие старого C1)*
5. **`ApplicationWindow`** — главный узел связности UI ↔ устройства ↔ персистентность ↔ Plus. *(ASK-5, ASK-6)*

---

## Uncertain / requires deeper check (агрегат)

| ID | Что |
|----|-----|
| U1 | Полный аудит ключей **`ProfileData`** ↔ все ветки **`setProfile`** / экспортов *(ASK-4)* |
| U2 | Полная карта **`ADD DEVICE:`** по репозиторию *(ASK-2)* |
| U3 | Где **`extraserialport`** vs **`serialport`** для extra-портов *(ASK-2)* |
| U4 | Инвентаризация **`uic/*.ui`** и горячих клавиш *(ASK-5)* |
| U5 | Гонки: все использования **`profileDataSemaphore`** / **`samplingSemaphore`** *(ASK-6)* |
| U6 | Поведение **`plus/schedule.py`** при cloud в scope *(ASK-3)* |

---

## Reuse / redesign / rewrite (сводка)

| Действие | Объекты |
|----------|---------|
| **Сохранить идею** | Поток опроса + обработка в «безопасном» контексте; блочные industrial reads; outbox + sync hash; пресеты машины (`.aset`); раздельно профиль vs настройки |
| **Извлекать осторожно** | **`modbusport` / S7 / WS**; отдельные asyncio-драйверы; куски **`sample_processing`** |
| **Переписать с нуля** | **`ApplicationWindow` как монолит**; **`devicefunctionlist`** без явного registry; **`sample_processing`** без Qt/mpl в том же слое; целевой UI |
| **Не как native MVP** | **`.alog`** через **`literal_eval`**; полный паритет Import menu / Events / Plus |
| **Исследовать глубже** | Лицензии при форке; полный Plus API; лимиты CSV/JSON |

---

# Раздел по `assemble_reports_prompt.md`

## Executive synthesis

См. [Executive summary](#executive-summary) выше — это и есть инженерный синтез без механического пересказа шести файлов.

## Resolved and unresolved contradictions

| ID | В чём расхождение | Отчёты | Проверка | Итог |
|----|-------------------|--------|----------|------|
| — | Опрос vs облако | ASK-1 vs ASK-3 | Plus не дублирует SampleThread; DTO из профиля | **Согласовано** |
| — | Runtime vs сериализуемый снимок | ASK-1 vs ASK-4 | Живые буферы `qmc` vs `ProfileData` при save | **Согласовано** |
| C1 | «Центр модели = только roast_properties» | устар. формулировки vs код | `ProfileData` + `main.getProfile/setProfile` | **Разрешено** |
| U1 | Полный маппинг ключей профиля | ASK-4 | Трассировка save/load/export | **Открыто** |

Между **ASK-01…06** логических **противоречий по одним механизмам** не выявлено.

## System decomposition

| Блок | Суть | Отчёт |
|------|------|--------|
| Core logging / roast pipeline | ON/START, sampling, RoR, события, redraw | [ASK-1](./agent_01_core_logging.md) |
| Device layer | Serial/Modbus/S7/WS, `devicefunctionlist` | [ASK-2](./agent_02_device_layer.md) |
| Artisan Plus / sync | auth, queue, sync, DTO | [ASK-3](./agent_03_artisan_plus.md) |
| Data model / persistence | `ProfileData`, `.alog`, QSettings, I/O | [ASK-4](./agent_04_data_model.md) |
| UI / UX | main window, меню, роли | [ASK-5](./agent_05_ui_ux.md) |
| Architecture / extraction | coupling, rewrite vs extract | [ASK-6](./agent_06_architecture_risks.md) |

## Инженерная классификация подсистем

| Подсистема | Роль сейчас | Ценность для нового продукта | Связность | Рекомендация |
|------------|-------------|------------------------------|-----------|--------------|
| `canvas.py` sampling + metrics | Ядро логгера + mpl | Очень высокая | Очень высокая (Qt) | Идею scheduler+processor; **переписать** ядро |
| `comm.py` + `devicefunctionlist` | Мульти-драйверный опрос | Паритет оборудования | Очень высокая | **Извлекать осторожно**; каркас — **переписать** / плагины |
| Modbus / S7 / WS модули | Промышленные транспорты | Высокая (сегмент) | Средняя | **Сохранить идею** |
| `ProfileData` + get/setProfile | Единый snapshot | Совместимость / обмен | Очень высокая | **Нормализовать**; версии схемы |
| `util.serialize` / `.alog` | Legacy native | Импорт старых файлов | Привязка к literal | **Не MVP-native**; импорт опционально |
| QSettings + `.aset` | Настройки vs профиль | Разделение артефактов | Средняя | **Идею** сохранить; явная схема |
| `plus/*` | Облако, sync, scheduler | По продукту | Средняя (модуль) | Идею outbox+sync; **GPL/API**; scheduler — вне узкого MVP |
| `ApplicationWindow` + меню | UX shell | Навигация | Очень высокая | **Переписать** UI; **UI_MODE** / роли — идея |
| Properties + Events | Метаданные и автоматизация | По ролям разная | Высокая | Basic/Expert; полный Events — engineer |

## Рамка будущего продукта (исследовательский вывод)

| Категория | Вывод |
|-----------|--------|
| **Ядро** | Ряды измерений + таймлайн фаз/событий + метаданные партии + сохраняемый snapshot; конфигурируемый опрос устройств. |
| **Перегруз** | Монолит **`ProfileData` + `setProfile`**; **`sample_processing` + Qt/mpl**; размер **`main.py`**; матрица Import; Events без ролей. |
| **Reusable (концепции)** | Scheduler + процессор; блочные industrial-клиенты; outbox + sync hash; профиль ≠ machine settings. |
| **Risky** | Паритет всех драйверов; **`literal_eval`**; неявная эволюция ключей; форк Plus без юр. оценки. |
| **Не тянуть в узкий MVP** | Полный Import; полный **`EventsDlg`**; полный Plus+scheduler; нативный `.alog` как основной формат нового приложения. |

## Risk map

| Риск | Источник (ASK) |
|------|----------------|
| Объём и хрупкость `setProfile`/`getProfile` | ASK-4, ASK-6 |
| Семафоры/гонки в sampling | ASK-1, ASK-6 |
| Fan-out `devicefunctionlist` / ADD DEVICE | ASK-2 |
| GPL + неформализованный Plus API | ASK-3 |
| Перегруз UX и связь диалогов с `aw.qmc` | ASK-5, ASK-6 |
| `literal_eval` на пользовательских файлах | ASK-4, ASK-6 |

## Questions for product brief stage

- **Транспорт MVP:** serial-only vs Modbus vs фиксированный список машин?
- **Облако:** нужен ли функционал уровня artisan.plus в v1?
- **Миграция:** требуемый паритет с `.alog` / полями `ProfileData`?
- **Платформа:** только desktop vs headless/logger-сервис?
- **Роли:** Novice/Roaster/Engineer vs один UI с advanced toggle?

---

## Индекс ASK-артефактов

| Файл | Тема |
|------|------|
| [`agent_01_core_logging.md`](./agent_01_core_logging.md) | Pipeline сессии, sampling, RoR, график |
| [`agent_02_device_layer.md`](./agent_02_device_layer.md) | Оборудование, протоколы, polling |
| [`agent_03_artisan_plus.md`](./agent_03_artisan_plus.md) | Облако, auth, sync, DTO |
| [`agent_04_data_model.md`](./agent_04_data_model.md) | `ProfileData`, persistence, I/O |
| [`agent_05_ui_ux.md`](./agent_05_ui_ux.md) | UI map, workflow, роли |
| [`agent_06_architecture_risks.md`](./agent_06_architecture_risks.md) | Coupling, extract vs rewrite |

---

*Конец master-report.*
