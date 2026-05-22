# ASK-2 — Device layer / Modbus / serial / equipment abstraction

**Объект:** Artisan / Roaster Scope (`src/artisanlib`)  
**Дата:** 2026-03-20  
**Правила:** наблюдение по коду; якоря — классы/функции в репозитории.

---

## Executive summary

Слой устройств центрирован на **`serialport` в `comm.py`**: гигантская таблица **`devicefunctionlist`** — список callables **`() -> (time, t1, t2)`**, индексируемый номером «девайса» **`qmc.device`**. Опрос идёт из **`SampleThread.sample()`** → **`sample_main_device()`** / **`sample_extra_device()`** в `canvas.py`: main читает `aw.ser.devicefunctionlist[...]`, extras — `aw.extraser[i].devicefunctionlist[...]`. Отдельные транспорты вынесены в **`modbusport.py`**, **`s7port`** (в `comm.py` или отдельный модуль — см. импорты `main.py`), **`wsport`**: экземпляры висят на **`ApplicationWindow`** (`self.ser`, `self.modbus`, `self.s7`, `self.ws`, `self.extraser`). Добавление оборудования по коду помечено тегом **`ADD DEVICE:`** (комментарий в `comm.py` у `devicefunctionlist`). Изоляция для нового продукта **низкая**: диспетчер и сотни протоколов сшиты с индексами и глобальным контекстом окна.

---

## Scope

Подключения оборудования, диспетчер чтения, Modbus/S7/WebSocket/serial branches, polling, типовая процедура добавления драйвера, reuse vs rewrite.

---

## Supported connection types

| Protocol / transport | Где реализовано | Для чего | Зрелость / интеграция |
|----------------------|-----------------|----------|------------------------|
| Serial / USB (vendor protocols) | `comm.py` — методы `fujitemperature`, `HH806AU`, `ARDUINOTC4`, Phidget, … + `serialport` | Main/extra датчики через `devicefunctionlist` | Очень высокая связка с `ApplicationWindow` / `qmc.device` |
| Modbus (RTU/TCP/UDP и варианты) | `modbusport.py` + ветки `MODBUS`, `MODBUS_34`, … в `devicefunctionlist` | Температуры/регистры через общий poll | Сильная; тип хоста/порта разруливается из `main.py` (machine setup) |
| Siemens S7 | `S7`, `S7_34`, … в `devicefunctionlist` (`comm.py`) | Промышленные PLC | Сильная |
| WebSocket | `wsport` + использование в конфиге окна | Сетевой транспорт | Средняя–высокая |
| Внешняя программа / callprogram | слоты `callprogram*` в списке | Кастомные бинарники | Высокая специфичность Artisan |
| Симулятор | `canvas.sample_main_device` — ветка `aw.simulator` | Тест/UI без железа | Изолированнее, но всё через `canvas` |

---

## Device abstraction map

- **Не классический интерфейс `Device`**: вместо этого **индекс → callable** на экземпляре `serialport` (main) или каждого `extraser[i]` (extras).
- **`serialport`** (`comm.py`): и main (`self.ser`), и каждый элемент **`self.extraser`** — это **`serialport(self)`** — ```1790:1790:src/artisanlib/main.py```, ```15652:15652:src/artisanlib/main.py```. У всех один и тот же тип **`devicefunctionlist`**: **`list[Callable[..., tuple[float,float,float]]]`** (индекс = номер устройства) — ```377:377:src/artisanlib/comm.py```; extra читает **`extraser[i].devicefunctionlist[extradevices[i]]()`** — ```19611:19612:src/artisanlib/canvas.py```.
- **`extraserialport`** (`comm.py`) — отдельный класс с `devicefunctionlist: dict[...]` — ```7459:7459:src/artisanlib/comm.py```; в типичном потоке `main.py` extra-порты создаются как **`serialport`**, не он (уточнять, если ветка кода использует `extraserialport`).
- **Выбор реализации чтения:** `tgraphcanvas.sample_main_device` вызывает `self.aw.ser.devicefunctionlist[self.aw.qmc.device]()` при отсутствии симулятора — ```19593:19607:src/artisanlib/canvas.py```.
- **Extra-каналы:** `sample_extra_device` — ```19609:19620:src/artisanlib/canvas.py```.

---

## Modbus findings

- Логика вынесена в **`src/artisanlib/modbusport.py`** (отдельный модуль от монолита `comm`, но по-прежнему получает ссылку на окно/контекст при создании в `main.py`).
- Устройство **29 / MODBUS** и производные индексы — строки в **`devicefunctionlist`** в `comm.py` ```407:411:src/artisanlib/comm.py``` и далее.
- В `main.py` есть ветвления по типу Modbus (TCP/UDP vs serial) при machine setup — см. использование `self.modbus.type`, `self.modbus.host`, `self.modbus.comport` (напр. ```5876:5920:src/artisanlib/main.py```).

---

## Polling and write pipeline

1. **`Athreadserver` / `SampleThread`** крутит цикл с `delay`, пока `flagon` (см. ASK-1).
2. **`sample()`** берёт lock `samplingSemaphore`, вызывает **`sample_main_device`** и для каждого extra — **`sample_extra_device`**, затем **`sample_processingSignal.emit(...)`** — ```19622:19670:src/artisanlib/canvas.py```.
3. **Запись в оборудование** (OUT): разрозненные вызовы из `main.py` (пример Phidget PWM/timer — ```5443:5447:src/artisanlib/main.py```); универсального «write pipeline» как у read-table нет в одном месте.

---

## Adding new equipment: real process

По комментарию в коде:

```375:376:src/artisanlib/comm.py
        # ADD DEVICE: to add a device you have to modify several places. Search for the tag "ADD DEVICE:" in the code (canvas.py, comm.py, devices.py)
        # - add to self.devicefunctionlist
```

Ожидаемые шаги (подтверждено только наличием тега и структурой списка): новый callable в `devicefunctionlist`, правки в `devices.py` / UI выбора устройства / `canvas.py`. Полный чеклист — отдельный grep по `ADD DEVICE:`.

---

## Reuse analysis

| Подсистема | Где | Изолируемость | Концепция reuse | Рекомендация |
|------------|-----|---------------|-----------------|--------------|
| `modbusport` / S7 / WS клиенты | `modbusport.py`, ветки в `comm` | Средняя | Блочное чтение регистров, хост/порт конфиг | **Идеи сохранить**; код тащить осторожно (лицензия, coupling) |
| `devicefunctionlist` таблица | `comm.py` | Низкая | «Реестр драйверов по id» | **Перепроектировать**: явный registry + интерфейсы |
| `serialport` + сотни протоколов | `comm.py` | Очень низкая | Паритет с рынком | **Переписать** целевой набор; не тащить всё |
| Async-слой (если используется для сетей) | `async_comm` и адаптеры (см. проект) | Выше среднего | Очереди, неблокирующий I/O | **Извлекать выборочно** |

---

## Findings (кратко)

- Один **индекс `qmc.device`** определяет, какая функция читает ET/BT; extras — параллельные индексы `qmc.extradevices[i]`.
- **Simulator** подменяет чтение без `devicefunctionlist` — удобно для UI, но усложняет тестирование железа.
- **Machine menu / `.aset`** — способ пресетов машины (связка с конфиг меню в `main.py`, см. `machineMenu`).

---

## Key files

| Файл | Зачем |
|------|--------|
| `src/artisanlib/comm.py` | `devicefunctionlist`, основная масса драйверов, `serialport` |
| `src/artisanlib/canvas.py` | `sample_main_device`, `sample_extra_device`, `sample()` |
| `src/artisanlib/main.py` | `self.ser`, `modbus`, `s7`, `ws`, `extraser`, machine setup |
| `src/artisanlib/modbusport.py` | Modbus транспорт и настройки каналов |

---

## Confirmed conclusions

- Polling завязан на **`SampleThread`** и **`devicefunctionlist[qmc.device]`** — см. цитаты выше.
- Modbus/S7/WS живут как отдельные объекты на окне + слоты в общей таблице.

---

## Uncertain / requires deeper check

- Полная карта **`ADD DEVICE:`** по всем файлам.
- Где именно используется класс **`extraserialport`** vs повсеместный **`serialport`** для extra-портов.
- Детальный аудит **async** пути для каждого транспорта.

---

## Reuse / redesign / rewrite

- **Брать идею:** табличный/preset конфиг машины; отдельные модули для промышленных протоколов.
- **Переосмыслить:** единый интерфейс `SamplerChannel` + DI вместо индексов в глобальном окне.
- **Писать заново:** монолитный `comm.py` как единственный центр совместимости.

---

## Open questions

- Минимальный набор драйверов для целевого сегмента нового продукта?
- Нужен ли **headless** sampler без Qt в MVP?
