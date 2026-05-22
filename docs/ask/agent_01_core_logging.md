# ASK-1 — Core logging / roast session pipeline

**Объект:** Artisan / Roaster Scope (`src/artisanlib`)  
**Дата:** 2026-03-20  
**Правила:** только наблюдение по исходникам, без догадок без якорей в коде.

---

## Executive summary

Жизненный цикл мониторинга и записи централизован в классе графика **`tgraphcanvas` в `canvas.py`**: флаги **`flagon`** (опрос включён) и **`flagstart`** (идёт запись в профиль). Поток **`SampleThread`** снимает показания с main/extra устройств и по сигналу вызывает **`sample_processing()`** в GUI-потоке; там же считаются RoR, автособытия и обновляются массивы рядов. Точки входа с панели — **`ApplicationWindow` в `main.py`** (кнопки ON/START и маркеры фаз). Персистентность после сессии — через **`getProfile` / `serialize`** (см. ASK-4 / master-report), не в этом файле.

---

## 1. Где начинается lifecycle roast session

| Этап | Якорь | Суть |
|------|--------|------|
| Пользователь жмёт ON | `main.py` → `qmc.ToggleMonitor` | ```3222:3222:src/artisanlib/main.py``` |
| Мониторинг включается | `canvas.py` → `OnMonitor`: `flagon = True`, `createSampleThread()` | ```13437:13479:src/artisanlib/canvas.py``` |
| Пользователь жмёт START | `main.py` → `qmc.ToggleRecorder` | ```3237:3237:src/artisanlib/main.py``` |
| Запись включается | `canvas.py` → `OnRecorder`: `flagstart = True`, `resetTimer()`, тайминг/дельты | ```14188:14237:src/artisanlib/canvas.py``` |
| Останов записи | `ToggleRecorder` (ветка STOP) → `OffRecorder`: `flagstart = False` | `OffRecorder`: ```14296:14311:src/artisanlib/canvas.py```; `ToggleRecorder`: ```14368:14404:src/artisanlib/canvas.py``` |
| Останов мониторинга | `OffMonitor` / `OffMonitorCloseDown`: `flagon = False`, разрыв потока | см. `OffMonitor` в том же файле после `OnMonitor` |

**Цепочка `newRoast` (пакетная логика):** `ApplicationWindow.newRoast` / `startNewRoast` — валидация CHARGE/DROP, при необходимости OFF монитора, затем `ToggleRecorder`.

---

## 2. Как устроен сбор данных (polling / sampling)

1. **`Athreadserver.createSampleThread`** создаёт `SampleThread`, соединяет `sample_processingSignal` с `qmc.sample_processing`.  
   — ```19766:19771:src/artisanlib/canvas.py```

2. **`SampleThread.run`**: цикл с интервалом `delay`, пока `flagon`; внутри вызывается `sample()`.

3. **`sample()`**:  
   - читает main device: `sample_main_device()` → `aw.ser.devicefunctionlist[device]()`;  
   - для каждого extra: `sample_extra_device(i)`;  
   - эмитит **`sample_processingSignal(local_flagstart, temp1_readings, temp2_readings, timex_readings)`**.  
   — ```19623:19670:src/artisanlib/canvas.py```

4. **`sample_processing()`** (явно: *в GUI thread, не в sample thread*):  
   - `profileDataSemaphore.tryAcquire` — при неуспехе раунд пропускается;  
   - разные целевые буферы при `local_flagstart` vs только мониторинг (`on_timex`, `on_temp1`, …);  
   - фильтры входа, маппинг ET/BT (`temp1`/`temp2` по комментарию в слотах класса), extra-каналы, PID update, alarms, автособытия;  
   - в конце **`updategraphicsSignal.emit()`**.  
   — ```4657:4665:src/artisanlib/canvas.py``` (начало + комментарий потока), ```5346:5347:src/artisanlib/canvas.py``` (emit)

**Пауза цикла:** `ApplicationWindow.sample_loop_running` может временно отключать вызов `sample()` внутри потока (см. использование в `SampleThread.run`).

---

## 3. Как считаются метрики (RoR и др.)

- **RoR:** `compute_ror()` — окно по `deltaTempSamples`, опционально **polyfit** (`polyfitRoRcalc`), иначе **`compute_ror_simple`** (slope × 60 → °/мин).  
  — ```4623:4652:src/artisanlib/canvas.py```, ```4614:4621:src/artisanlib/canvas.py```

- В **`sample_processing`**: после сглаживания `tstemp1/2` вычисляются `rateofchange1/2`, при необходимости **DeltaET/BT math expressions**, сглаживание delta, лимиты отображения; результат в **`sample_delta1/2`** и обновление линий RoR при записи.  
  — ```4977:5043:src/artisanlib/canvas.py``` (фрагмент с `compute_ror` и append в delta)

---

## 4. События roast timeline

| Механизм | Где | Примечание |
|----------|-----|------------|
| Индексы фаз CHARGE…DROP | `timeindex[]` | Устанавливаются в `markCharge`, `markDrop`, `mark1Cstart`, … |
| UI → обработчики | `main.py` | CHARGE/DROP/FC/SC → `qmc.mark*` | ```3273:3278:src/artisanlib/main.py``` (CHARGE/DROP; FC — строки выше в том же блоке) |
| Реализация маркеров | `canvas.py` | Пример: `markCharge` ```14422:```, `mark1Cstart` ```14730:```, `markDrop` ```15183:``` |
| Произвольные события | `addEvent` → списки `specialevents*` | ```19046:19050:src/artisanlib/canvas.py``` |
| Автодетекция | внутри `sample_processing` | auto CHARGE/DROP (BT break), TP, auto DRY/FCs по порогам — см. блок около ```5075:5122:src/artisanlib/canvas.py``` |

---

## 5. Обновление графика / redraw

- **Полный пересчёт графика:** `redraw()` — matplotlib axes, фоны, двухосевой режим RoR и т.д.  
  — ```9396:9396:src/artisanlib/canvas.py```

- **После каждого сэмпла (в записи/мониторинге):** `updategraphics()` — LCD, частичные обновления линий, bitblit где применимо; блокировка `updateGraphicsSemaphore`.  
  — ```5513:5516:src/artisanlib/canvas.py```

- **Отложенный полный redraw:** `main.py` `redrawTimer` → `redraw_action` → `qmc.redraw(False, False)`.  
  — ```5263:5265:src/artisanlib/main.py```

- **Фон для bitblit:** `updateBackground()` (вызовы из маркеров/аннотаций) — см. определение в `canvas.py` (~```2793```).

---

## 6. Минимальное ядро нового логгера (извлечение смысла)

Без Qt/Matplotlib на уровне концепции:

1. Дискретная **state machine**: monitoring on/off, recording on/off.  
2. **Scheduler** с фиксированным интервалом и skip при lag.  
3. **Acquisition** (main + N extras) → очередь/сигнал → **single processor** (фильтры, ряды, производные).  
4. **Event store**: фиксированные фазы (индексы во времени) + произвольные события.  
5. **Observer** для UI/файла/сокета (отделённо от processor).

---

## 7. Reusable vs legacy vs переписать

| Классификация | Что |
|---------------|-----|
| **Сохранить идею** | отдельный sampler thread + обработка в «главном» контексте; семафоры против гонок; окно RoR + polyfit fallback |
| **Извлекать осторожно** | куски `sample_processing` (слишком большая функция, много ветвлений устройств) |
| **Legacy / высокая связность** | `canvas.py` как сцепление domain + Qt + matplotlib + alarms + PID |
| **Переписать с нуля** | тот же модуль как единое «ядро» без декомпозиции — для нового продукта нужен новый слой границ |

---

## Таблица компонентов (обязательная)

| Компонент | Где найден | Для чего нужен | Обязателен для MVP | Можно ли отделить | Комментарий |
|-----------|------------|----------------|-------------------|-------------------|-------------|
| UI: ON/START/фазовые кнопки | `main.py` | Запуск режимов | Да* | Да | *MVP может заменить на API |
| `ToggleMonitor` / `OnMonitor` | `canvas.py` | Включение опроса | Да | Частично | Завязан на Qt/UI |
| `ToggleRecorder` / `OnRecorder` | `canvas.py` | Запись рядов | Да | Частично | |
| `SampleThread` + `sample()` | `canvas.py` | Периодический опрос | Да | Да | Ядро паттерна |
| `sample_processing()` | `canvas.py` | Фильтры, ряды, RoR, автоивенты | Да | Частично | Требует распила |
| `compute_ror` | `canvas.py` | Метрика RoR | Да для parity | Да | Чистая логика |
| `updategraphics` / `redraw` | `canvas.py` | Отрисовка | Нет для headless | Да | Заменяется renderer-ом |
| `timeindex` + `mark*` | `canvas.py` | Фазы обжарки | Да | Да | Доменная модель |
| `addEvent` / specialevents | `canvas.py` | Произвольные события | Зависит от продукта | Да | |

---

## Файлы и функции для следующего исследования

- `canvas.py`: `OffMonitor`, `OffRecorder`, `reset()`, `timealign()`, `BTbreak`, `playbackevent` (follow background)
- `main.py`: `getProfile`, `automaticsave`, интеграция Plus при записи
- `comm.py`: привязка `devicefunctionlist` к конкретным драйверам

---

*Конец ASK-1.*
