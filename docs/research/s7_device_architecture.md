# S7 Device Architecture in Artisan

## Executive summary

S7-интеграция в Artisan реализована в первую очередь в `src/artisanlib/s7port.py` через класс `s7port`, а не как отдельный чистый protocol layer. По коду это смесь transport/session management, PLC addressing, value read/write API, PID-specific write helpers и shared app coupling через `ApplicationWindow`. Основание: `src/artisanlib/s7port.py:40`, `src/artisanlib/main.py:1785`.

Цепочка конфигурации из `.aset` в runtime идет через QSettings group `[S7]`: `main.py` читает поля секции в `self.s7.*`, UI-диалог `ports.py` редактирует эти же поля, а polling/read path затем использует их в `comm.py:S7read()` и `s7port.py`. Основание: `src/artisanlib/main.py:18536-18564`, `src/artisanlib/main.py:24810-24834`, `src/artisanlib/comm.py:3092`, `src/artisanlib/s7port.py:265`.

S7 в Artisan не выглядит как общий abstraction layer, отделенный от UI. Между UI и runtime есть объект `self.s7`, но он напрямую зависит от `aw.qmc`, `aw.sendmessage()`, `aw.seriallogflag` и PID/event actions. Основание: `src/artisanlib/s7port.py:40-44`, `src/artisanlib/s7port.py:224-259`, `src/artisanlib/s7port.py:310-356`, `src/artisanlib/main.py:10028-10162`, `src/artisanlib/pid_control.py:1488-1541`.

Наиболее полезные идеи для нового проекта по коду:

- отдельный runtime object для S7 connection state и mapping tables;
- batch polling optimizer по активным адресам;
- явное разделение raw PLC addressing (`area/db_nr/start/type`) и channel post-processing (`div/mode`).

Наиболее проблемные места:

- прямое сращивание backend с UI/error surface;
- command path через строки `setDBint(...)` / `getDBfloat(...)` и `eval()`;
- special-case device IDs (`79`, `80`, `81`, `82`, `110`, `151`) вместо более чистой channel-group abstraction;
- смешение connection, addressing, conversion, PID-control и runtime app concerns в одном классе.

## Where S7 is implemented

### Основные файлы, модули, классы

1. `src/artisanlib/s7port.py`
   Основной backend: `class s7port`. Хранит connection state, конфигурацию каналов, optimizer cache, PID registers и методы read/write. Основание: `src/artisanlib/s7port.py:40-44`, `src/artisanlib/s7port.py:48-110`.

2. `src/artisanlib/s7client.py`
   Узкий snap7 wrapper `S7Client`, который только патчит `destroy()` для избежания исключения при незагруженной shared library. Основание: `src/artisanlib/s7client.py:3-15`.

3. `src/artisanlib/comm.py`
   Runtime bridge from device layer to roast sampling. Здесь S7 зарегистрирован в `devicefunctionlist`, а `S7()`, `S7_34()`, ... вызывают `S7read()`, который маппит PLC readings в ET/BT и extra channels. Основание: `src/artisanlib/comm.py:407`, `src/artisanlib/comm.py:457-460`, `src/artisanlib/comm.py:488`, `src/artisanlib/comm.py:529`, `src/artisanlib/comm.py:1506-1529`, `src/artisanlib/comm.py:3092-3112`.

4. `src/artisanlib/ports.py`
   UI/settings entry point. Tab S7 создает edit/combo controls для `host/port/rack/slot`, 12 каналов (`area/db/start/type/div/mode`) и PID block (`PID_area`, `PID_*_register`, `PID_*_action`). Основание: `src/artisanlib/ports.py:924-1199`.

5. `src/artisanlib/main.py`
   Создает `self.s7`, читает/сохраняет `[S7]` через QSettings, переносит настройки из dialog в runtime, использует S7 command strings в event actions и отключает S7 на shutdown. Основание: `src/artisanlib/main.py:1785`, `src/artisanlib/main.py:18536-18564`, `src/artisanlib/main.py:20504-20526`, `src/artisanlib/main.py:24810-24834`, `src/artisanlib/main.py:21452-21454`, `src/artisanlib/main.py:10028-10162`.

6. `src/artisanlib/pid_control.py`
   Отдельный PID layer, который определяет S7 как external PID controller type `2`, вызывает `self.aw.s7.setTarget()` / `setPID()` и запускает `PID_ON_action` / `PID_OFF_action` через общий event command path. Основание: `src/artisanlib/pid_control.py:1279-1288`, `src/artisanlib/pid_control.py:1488-1541`, `src/artisanlib/pid_control.py:1722-1738`, `src/artisanlib/pid_control.py:1875-1883`.

### Какой модуль отвечает за S7 backend

Основной backend-модуль: `src/artisanlib/s7port.py`.

Но строго по коду это не единственный слой:

- `s7port.py` делает connect/read/write/cache/retry/optimizer;
- `comm.py` решает, какие из 12 конфигурируемых S7 inputs попадают в текущий device readout;
- `main.py` и `ports.py` управляют настройками;
- `pid_control.py` использует S7 для external PID.

Поэтому точнее назвать это не “чистый backend-модуль”, а центральный runtime component внутри более широкой S7 integration path. Уверенность высокая.

### Это отдельный device driver, transport adapter, protocol layer или смесь

По коду это смесь:

- transport/session: `connect()`, `disconnect()`, `isConnected()`, `waitToEnsureMinTimeBetweenRequests()` в `s7port.py`;
- addressing/mapping storage: `area`, `db_nr`, `start`, `type`, `mode`, `div`;
- optimized polling cache: `updateActiveRegisters()`, `readActiveRegisters()`, `readingsCache`;
- low-level read/write API: `readInt/Float/Bool`, `writeInt/Float/Bool`, `maskWriteInt`;
- PID-specific convenience API: `setTarget()`, `setPID()`.

Основание: `src/artisanlib/s7port.py:48-110`, `src/artisanlib/s7port.py:124-159`, `src/artisanlib/s7port.py:176-259`, `src/artisanlib/s7port.py:265-356`, `src/artisanlib/s7port.py:362-745`.

## Runtime flow from `.aset` to connection

### Где читается S7-конфигурация из `.aset`

Artisan читает machine setup через `QSettings`; секция `[S7]` восстанавливается в `main.py`:

- `area`
- `db_nr`
- `start`
- `type`
- `mode`
- `div`
- `host`
- `port`
- `rack`
- `slot`
- `PID_area`
- `PID_db_nr`
- `PID_SV_register`
- `PID_p_register`
- `PID_i_register`
- `PID_d_register`
- `PID_OFF_action`
- `PID_ON_action`
- `PIDmultiplier`
- `SVmultiplier`
- `SVtype`
- `optimizer`
- `fetch_max_blocks`

Основание: `src/artisanlib/main.py:18536-18564`.

В реальных machine presets секция `[S7]` действительно содержит именно эти поля. Примеры:

- `src/includes/Machines/Giesen/WxA.aset`
- `src/includes/Machines/Probat/G_UG_control.aset`
- `src/includes/Machines/Kirsch+Mausser/PLC_control.aset`

Во всех них видны `area/db_nr/start/type/mode/div` и network fields `host/port/rack/slot`, а также PID block. Основание: просмотр секций `[S7]` в этих `.aset`.

### Как настройки из `.aset` попадают в runtime

Реальная цепочка:

1. При старте/загрузке setup `ApplicationWindow` уже имеет `self.s7 = s7port(self)`: `src/artisanlib/main.py:1782-1786`.
2. `main.py` читает QSettings group `S7` и заполняет поля этого объекта: `src/artisanlib/main.py:18536-18564`.
3. Dialog `ports.py` редактирует те же поля через widgets, привязанные к `self.aw.s7.*`: `src/artisanlib/ports.py:924-1199`.
4. После принятия dialog `main.py` копирует значения обратно из UI в `self.s7.*`: `src/artisanlib/main.py:24810-24834`.
5. Sampling path `comm.py:S7read()` использует `self.aw.s7.area/db_nr/start/type/mode/div`: `src/artisanlib/comm.py:3092-3112`.
6. Low-level read/write path `s7port.py` использует те же значения в `read_area()` / `write_area()`: `src/artisanlib/s7port.py:265-356`, `src/artisanlib/s7port.py:362-745`.

### Кто открывает соединение

Соединение открывает сам `s7port.connect()`: `src/artisanlib/s7port.py:198-259`.

Этот метод:

1. Создает `S7Client`, если `self.plc is None`: `src/artisanlib/s7port.py:200-205`.
2. Проверяет `isConnected()`: `src/artisanlib/s7port.py:208`.
3. Делает `plc.disconnect()` для fresh start: `src/artisanlib/s7port.py:212-217`.
4. Проверяет доступность TCP endpoint через `isOpen(self.host, self.port)`: `src/artisanlib/s7port.py:219`.
5. Вызывает `self.plc.connect(self.host, self.rack, self.slot, self.port)`: `src/artisanlib/s7port.py:223-227`.
6. При неудаче уничтожает client, создает новый и повторяет вторую попытку: `src/artisanlib/s7port.py:238-253`.
7. После connect пересчитывает `activeRegisterSequences`: `src/artisanlib/s7port.py:255`.

### Где хранится connection state

Внутри `s7port`:

- `plc`
- `is_connected`
- `commError`
- `last_request_timestamp`
- `COMsemaphore`
- `readingsCache`
- `activeRegisterSequences`

Основание: `src/artisanlib/s7port.py:43-44`, `src/artisanlib/s7port.py:99-110`.

### Есть ли reconnect model

Да, но она встроена в read/write path, а не вынесена в отдельный reconnect service.

Механика:

- каждый read/write сначала вызывает `connect()`;
- `connect()` делает fresh reconnect, если `isConnected()` возвращает `False`;
- после errors выставляется `commError = True`;
- при следующем удачном чтении/батч-чтении ошибка сбрасывается и выдается message `S7 Communication Resumed`.

Основание: `src/artisanlib/s7port.py:164-174`, `src/artisanlib/s7port.py:198-259`, `src/artisanlib/s7port.py:287-323`, `src/artisanlib/s7port.py:454-457`, `src/artisanlib/s7port.py:634-637`, `src/artisanlib/s7port.py:717-720`.

Уверенность высокая, но важно: отдельного background reconnect loop по коду не видно; reconnect лениво привязан к очередной операции.

## Address/value mapping model

### Как задаются адреса, области памяти и типы данных

S7 addressing model хранится в параллельных массивах длины `channels=12`:

- `area`
- `db_nr`
- `start`
- `type`
- `mode`
- `div`

Основание: `src/artisanlib/s7port.py:57-67`.

UI подтверждает ту же модель:

- `Area`: `[' ', 'PE', 'PA', 'MK', 'CT', 'TM', 'DB']`
- `Type`: `['Int', 'Float', 'IntFloat', 'Bool(0)' ... 'Bool(7)']`
- `Mode`: `- / C / F`
- `Factor`: `- / 1/10 / 1/100`

Основание: `src/artisanlib/ports.py:959-1035`.

`initArrays()` маппит numeric `area` values на snap7 `Area.PE/PA/MK/CT/TM/DB`: `src/artisanlib/s7port.py:114-123`.

### Где адреса S7 интерпретируются

Два ключевых места:

1. `s7port.updateActiveRegisters()`
   Интерпретирует channel config для optimizer-а. Для каждого активного канала вычисляет, какие byte registers реально нужно читать:
   - Bool: 1 byte at `start`
   - Int: `start` and `start+1`
   - Float / IntFloat: `start..start+3`

   Основание: `src/artisanlib/s7port.py:265-287`.

2. `comm.S7read()`
   Для каждой пары каналов выбирает low-level read method по `type`, затем применяет `processChannelData()` по `div` и `mode`: `src/artisanlib/comm.py:3092-3112`.

### Как обрабатываются scaling / offsets / conversions

В S7 path по коду есть:

- scaling только через `div`:
  - `0` = no scaling
  - `1` = `/10`
  - `2` = `/100`

- temperature mode conversion только через `mode`:
  - `1` -> channel data is Celsius
  - `2` -> Fahrenheit
  - `0` -> no temperature semantics

Это делается в `comm.processChannelData()`: `src/artisanlib/comm.py:3066-3081`.

Прямых offset fields для input channel mapping в S7 section по коду не найдено. Уверенность высокая.

### Как PLC values связываются с внутренними каналами Artisan

S7 channels организованы попарно:

- channels 1-2 -> device `S7` (`comm.S7()`)
- channels 3-4 -> `S7_34()`
- channels 5-6 -> `S7_56()`
- channels 7-8 -> `S7_78()`
- channels 9-10 -> `S7_910()`
- channels 11-12 -> `S7_1112()`

Основание: `src/artisanlib/comm.py:1506-1529`, `src/artisanlib/comm.py:3092-3112`.

`devicefunctionlist` регистрирует эти device families отдельными device IDs:

- `79` -> `self.S7`
- `80` -> `self.S7_34`
- `81` -> `self.S7_56`
- `82` -> `self.S7_78`
- `110` -> `self.S7_910`
- `151` -> `self.S7_1112`

Основание: `src/artisanlib/comm.py:457-460`, `src/artisanlib/comm.py:488`, `src/artisanlib/comm.py:529`.

Далее sampling thread вызывает device function, получает `(tx, t1, t2)` и пишет эти значения в runtime arrays. Эта последняя часть общая для всех устройств и идет через `SampleThread.sample()` -> `sample_processing()`. Основание: `src/artisanlib/canvas.py:19593-19606`, `src/artisanlib/canvas.py:19623-19664`, `src/artisanlib/canvas.py:4658-4719`.

### Есть ли единая модель mapping

Да, но она простая и реализована параллельными конфиг-массивами, а не object-per-channel model.

Минимальная фактическая mapping model:

- addressing: `area/db_nr/start`
- raw datatype: `type`
- operator-facing interpretation: `div/mode`
- channel grouping: pair index via `mode*2 ... mode*2+1` in `S7read()`

Основание: `src/artisanlib/s7port.py:57-67`, `src/artisanlib/comm.py:3092-3112`.

### Где разделяются machine/raw values и operator-facing values

Разделение проходит в `comm.py`:

1. `s7port.readInt/Float/Bool()` возвращают raw PLC-level values: `src/artisanlib/s7port.py:454-566`, `src/artisanlib/s7port.py:634-745`.
2. `comm.S7read()` выбирает правильный raw reader по `type`: `src/artisanlib/comm.py:3098-3106`.
3. `comm.processChannelData()` превращает raw value в operator-facing value через divider и temp-mode conversion: `src/artisanlib/comm.py:3066-3081`.

Это одно из более чистых мест в архитектуре S7 слоя. Уверенность высокая.

### Какие поля конфигурации обязательны

По коду обязательные для чтения канала:

- `area[i]` должно быть non-zero, иначе канал считается неактивным: `src/artisanlib/comm.py:3097`, `src/artisanlib/s7port.py:454`, `src/artisanlib/s7port.py:634`, `src/artisanlib/s7port.py:680`.
- `db_nr[i]`
- `start[i]`
- `type[i]`

Для network connection:

- `host`
- `port`
- `rack`
- `slot`

PID-specific fields обязательны только если используется external S7 PID:

- `PID_area != 0` для активации S7 external PID semantics: `src/artisanlib/pid_control.py:1279-1288`.

## Polling and reconnect model

### Как устроен polling

Основной polling flow:

1. Sampling thread вызывает `comm.S7(force=False)` для device `79`: `src/artisanlib/comm.py:1506-1511`.
2. `comm.S7()` фиксирует timestamp в `aw.extraS7tx` и вызывает `S7read(0, force)`: `src/artisanlib/comm.py:1506-1511`.
3. `S7read()` при `mode == 0` и `force == False` заранее вызывает `self.aw.s7.readActiveRegisters()`: `src/artisanlib/comm.py:3094-3096`.
4. `readActiveRegisters()`:
   - acquires `COMsemaphore`
   - clears cache
   - ensures connection
   - iterates over `activeRegisterSequences`
   - issues `read_area()` block reads
   - caches returned bytes

   Основание: `src/artisanlib/s7port.py:303-324`.
5. Затем `S7read()` читает пару нужных каналов уже из cache через `readInt/Float/Bool()`, если optimizer включен и cache hit произошел: `src/artisanlib/comm.py:3097-3112`, `src/artisanlib/s7port.py:454-477`, `src/artisanlib/s7port.py:634-654`, `src/artisanlib/s7port.py:680-698`.

### Как работает optimizer

`updateActiveRegisters()` строит список активных byte registers по всем сконфигурированным каналам и группирует их в sequences:

- `min_blocks(registers)` либо
- `max_blocks(registers, max_register_segment=100)` если `fetch_max_blocks=True`.

Основание: `src/artisanlib/s7port.py:265-287`.

Это дает два режима:

- gap-aware compact fetch;
- full block fetch between min and max register.

### Как обрабатываются timeouts / pacing / concurrency

Явные механизмы:

- `COMsemaphore` serializes access to PLC from read/write operations: `src/artisanlib/s7port.py:101`, использование во всех read/write methods.
- `min_time_between_requests = 0.04` и `waitToEnsureMinTimeBetweenRequests()` принудительно вставляют минимальную паузу между сетевыми запросами: `src/artisanlib/s7port.py:104-110`, `src/artisanlib/s7port.py:126-131`.
- `readRetries = 1`; single read и batch read повторяют запрос до исчерпания retry budget: `src/artisanlib/s7port.py:51`, `src/artisanlib/s7port.py:313-323`, `src/artisanlib/s7port.py:485-497`, `src/artisanlib/s7port.py:665-677`, `src/artisanlib/s7port.py:711-724`.

Отдельного configurable timeout handling в `s7port.py` не найдено; вероятно timeout behavior в основном наследуется от snap7 client. Это вывод с неполной уверенностью, потому что `S7Client` патчит только `destroy()`, а явной настройки request timeout в коде не видно. Основание: `src/artisanlib/s7client.py:3-15`.

### Error handling и reconnect

После read/write failures:

- ошибки логируются;
- `self.commError = True`;
- в recording mode ошибки также идут в `aw.qmc.adderror(...)`;
- при следующем успешном чтении генерируется `S7 Communication Resumed`.

Основание: `src/artisanlib/s7port.py:343-356`, `src/artisanlib/s7port.py:400-412`, `src/artisanlib/s7port.py:454-457`, `src/artisanlib/s7port.py:542-553`, `src/artisanlib/s7port.py:634-637`, `src/artisanlib/s7port.py:717-720`.

### Есть ли abstraction layer между UI и S7 runtime

Есть только тонкий object boundary `self.s7`, но полноценной изоляции нет.

Примеры прямой связности:

- `s7port.connect()` вызывает `self.aw.sendmessage(...)`: `src/artisanlib/s7port.py:230`, `src/artisanlib/s7port.py:248`.
- `s7port` пишет ошибки прямо в `self.aw.qmc.adderror(...)`: `src/artisanlib/s7port.py:325-356`, `src/artisanlib/s7port.py:379-412`, `src/artisanlib/s7port.py:454-457`, `src/artisanlib/s7port.py:542-553`, `src/artisanlib/s7port.py:634-637`, `src/artisanlib/s7port.py:717-720`.
- UI dialog напрямую читает и пишет `self.aw.s7.*`: `src/artisanlib/ports.py:924-1199`, `src/artisanlib/main.py:24810-24834`.

Итог: abstraction boundary слабая. Уверенность высокая.

### Насколько S7-код связан с UI/state

Сильно связан:

- с UI messages/errors;
- с `qmc.mode` для unit conversion;
- с device IDs в `comm.py` и `canvas.py`;
- с PID dialog / CONTROL button path;
- с generic event command strings.

Основание: `src/artisanlib/comm.py:3066-3081`, `src/artisanlib/canvas.py:4456-4463`, `src/artisanlib/canvas.py:13092-13105`, `src/artisanlib/pid_control.py:1488-1541`, `src/artisanlib/main.py:10028-10162`.

## Outgoing write path

### Поддерживает ли S7 backend запись

Да, не только читает.

Поддерживаемые write operations:

- `writeInt()`
- `maskWriteInt()`
- `writeFloat()`
- `writeBool()`

Основание: `src/artisanlib/s7port.py:362-450`.

Также есть convenience writes для PID:

- `setPID()`
- `setTarget()`

Основание: `src/artisanlib/s7port.py:136-159`.

### Где формируются outgoing S7 writes

Есть два основных write paths.

#### 1. Generic operator/event command path

`main.py:eventaction()` для action `15` ("S7 Command") парсит строковые команды:

- `setDBint(db,start,value)`
- `msetDBint(db,start,andMask,orMask,value)`
- `setDBfloat(db,start,value)`
- `setDBbool(db,start,bit,value)`
- `getDBint/getDBfloat/getDBbool(...)`

Затем вызывает `self.s7.writeInt/maskWriteInt/writeFloat/writeBool/readInt/readFloat/readBool`.

Основание: `src/artisanlib/main.py:10028-10162`.

Это тот же путь, который использует button/slider/event action system. Основание: `src/artisanlib/main.py:8874`, `src/artisanlib/main.py:8883`, `src/artisanlib/main.py:10028`.

#### 2. External PID control path

Если `externalPIDControl() == 2`, то:

- `pidOn()`/`pidOff()` запускают `PID_ON_action` / `PID_OFF_action` через `eventaction(15, ...)`: `src/artisanlib/pid_control.py:1488-1541`
- `setSV()` вызывает `self.aw.s7.setTarget(...)`: `src/artisanlib/pid_control.py:1722-1738`
- `confPID()` вызывает `self.aw.s7.setPID(...)`: `src/artisanlib/pid_control.py:1875-1883`

### Где проходит путь operator action -> low-level write

Основная цепочка для generic actions:

1. UI/button/slider/event вызывает `eventactionx()` / `eventaction()`: `src/artisanlib/main.py:8874`.
2. Для action `15` строка команды разбирается в `main.py`: `src/artisanlib/main.py:10028-10162`.
3. Низкоуровневые методы `s7port.write*()` выполняют read-modify-write against PLC через snap7: `src/artisanlib/s7port.py:362-450`.

Цепочка для PID:

1. Operator action in PID dialog / CONTROL state.
2. `pid_control.externalPIDControl() == 2`: `src/artisanlib/pid_control.py:1279-1288`.
3. `pidOn/pidOff/setSV/confPID` route to S7-specific command or helper: `src/artisanlib/pid_control.py:1488-1541`, `src/artisanlib/pid_control.py:1722-1738`, `src/artisanlib/pid_control.py:1875-1883`.
4. Those helpers call `s7port.write*()`: `src/artisanlib/s7port.py:136-159`, `src/artisanlib/s7port.py:362-450`.

### Насколько запись в PLC завязана на UI

Сильно:

- generic writes кодируются строками в event/button/slider config;
- PID ON/OFF state tied to `buttonCONTROL` style updates и message flow;
- backend reports errors directly to UI.

Основание: `src/artisanlib/main.py:10028-10162`, `src/artisanlib/pid_control.py:1488-1541`, `src/artisanlib/s7port.py:224-259`, `src/artisanlib/s7port.py:343-356`.

## Coupling / architectural weaknesses

1. `s7port` совмещает transport, cache optimizer, mapping storage, PID helper logic и UI reporting.
   Основание: `src/artisanlib/s7port.py:40-159`, `src/artisanlib/s7port.py:176-745`.

2. Mapping model реализован как параллельные массивы, а не typed channel definitions.
   Основание: `src/artisanlib/s7port.py:57-67`.

3. Device family расширяется через fixed device IDs (`79/80/81/82/110/151`) и pair-based functions `S7_34`, `S7_56`, ...
   Основание: `src/artisanlib/comm.py:457-460`, `src/artisanlib/comm.py:488`, `src/artisanlib/comm.py:529`.

4. Command write path использует строковый DSL и `eval()`.
   Основание: `src/artisanlib/main.py:10043-10094`.

5. UI/state coupling идет напрямую через `aw.sendmessage`, `aw.qmc.adderror`, `seriallogflag`, `qmc.mode`.
   Основание: `src/artisanlib/s7port.py:224-259`, `src/artisanlib/s7port.py:343-356`, `src/artisanlib/comm.py:3066-3081`.

6. Reconnect model встроен в каждую read/write операцию, а не выделен в connection supervisor.
   Основание: `src/artisanlib/s7port.py:198-259`, `src/artisanlib/s7port.py:303-324`, `src/artisanlib/s7port.py:362-745`.

## What to carry into the new product

### Что оставить как идею

1. Отдельный S7 runtime object с собственным connection state.
   Почему: в Artisan хотя бы есть единая точка `self.s7`, через которую проходит весь S7 I/O.

2. Batch polling optimizer по активным адресам.
   Почему: `updateActiveRegisters()` + `readActiveRegisters()` дают понятный reusable concept для уменьшения числа PLC round-trips.

3. Явное разделение raw read и post-processing.
   Почему: `readInt/Float/Bool()` + `processChannelData()` задают полезную границу между PLC data и operator-facing values.

### Что переосмыслить

1. Конфигурационную модель каналов.
   Почему: `area/db_nr/start/type/mode/div` хорошая основа, но лучше представлять это structured channel mapping objects, а не параллельными массивами.

2. Связь external PID и device layer.
   Почему: сами PID registers и target scaling можно сохранить как идею, но control path должен идти через typed commands, а не через UI-bound event strings.

3. Error/reporting boundary.
   Почему: backend should emit domain errors/events, а не напрямую писать в UI message bus.

### Что переписать

1. String command DSL с `eval()`.
   Почему: высокий coupling, слабая типизация, плохая тестируемость.

2. Special-case device IDs для S7 channel groups.
   Почему: лучше иметь N logical S7 channels/ports, а не `S7`, `S7_34`, `S7_56`, ...

3. Monolithic `s7port`.
   Почему: connection/transport, addressing, conversion, cache, PID helpers и UI coupling лучше разделить на отдельные сервисы.

## Table 1 — S7 runtime map

| Компонент | Где найден | Роль | Входы | Выходы | Насколько связан с UI |
| --- | --- | --- | --- | --- | --- |
| `s7port` | `src/artisanlib/s7port.py:40` | Central S7 runtime object | Config from `self.s7.*`, read/write calls | PLC reads/writes, cache, UI messages/errors | Высоко |
| `S7Client` | `src/artisanlib/s7client.py:9` | Thin patched snap7 client | snap7 shared lib | `connect/read_area/write_area` backend | Низко |
| `comm.S7()` / `S7read()` | `src/artisanlib/comm.py:1506`, `src/artisanlib/comm.py:3092` | Sampling bridge from S7 to Artisan channels | `self.aw.s7.*`, current roast mode | `(tx,t1,t2)` for sampling thread | Средне |
| `ports.py` S7 tab | `src/artisanlib/ports.py:924-1199` | UI config editor | Current `self.aw.s7.*` | Dialog values written back to runtime | Очень высоко |
| QSettings load/save for `[S7]` | `src/artisanlib/main.py:18536-18564`, `src/artisanlib/main.py:20504-20526` | Persistence of S7 config | `.aset` / settings store | `self.s7.*` | Средне |
| Dialog apply path | `src/artisanlib/main.py:24810-24834` | Copies UI values into runtime | Widgets from S7 tab | Updates `self.s7.*` | Очень высоко |
| Generic S7 command path | `src/artisanlib/main.py:10028-10162` | Operator action -> low-level S7 read/write | Command strings | `s7.write*()` / `s7.read*()` | Очень высоко |
| External PID via S7 | `src/artisanlib/pid_control.py:1279-1288`, `src/artisanlib/pid_control.py:1488-1541`, `src/artisanlib/pid_control.py:1722-1738`, `src/artisanlib/pid_control.py:1875-1883` | Hardware PID control over S7 | PID config + operator actions | S7 writes and control state | Очень высоко |

## Table 2 — Mapping from config to runtime

| Поле конфигурации | Где читается | Как используется | На что влияет в runtime |
| --- | --- | --- | --- |
| `host` | `src/artisanlib/main.py:18548` | Passed into `s7port.connect()` and `isOpen()` | TCP destination |
| `port` | `src/artisanlib/main.py:18549` | Passed into `isOpen()` and `plc.connect(..., port)` | TCP destination |
| `rack` | `src/artisanlib/main.py:18550` | Passed into `plc.connect()` | PLC session addressing |
| `slot` | `src/artisanlib/main.py:18551` | Passed into `plc.connect()` | PLC session addressing |
| `area[]` | `src/artisanlib/main.py:18536` | Decides S7 area and channel active/inactive state | Read/write addressing and channel enable |
| `db_nr[]` | `src/artisanlib/main.py:18538` | DB number for each channel | Read/write addressing |
| `start[]` | `src/artisanlib/main.py:18540` | Start byte offset for each channel | Read/write addressing |
| `type[]` | `src/artisanlib/main.py:18542` | Selects int/float/intFloat/bool read path and register width | Raw decode and optimizer register ranges |
| `mode[]` | `src/artisanlib/main.py:18544` | Interpreted in `processChannelData()` as `C/F/none` | Temperature conversion and non-temp hints |
| `div[]` | `src/artisanlib/main.py:18546` | Interpreted in `processChannelData()` as `/10` or `/100` | Scaling of operator-facing values |
| `optimizer` | `src/artisanlib/main.py:18563` | Enables `readActiveRegisters()` cache path | Batch polling behavior |
| `fetch_max_blocks` | `src/artisanlib/main.py:18564` | Switches `min_blocks()` vs `max_blocks()` | Polling block shape |
| `PID_area` | `src/artisanlib/main.py:18552` | Enables S7 external PID when non-zero | PID control mode selection |
| `PID_db_nr` | `src/artisanlib/main.py:18553` | Used by `setPID()` / `setTarget()` | PID write target DB |
| `PID_SV_register` | `src/artisanlib/main.py:18554` | Used by `setTarget()` | External PID setpoint write register |
| `PID_p_register` / `PID_i_register` / `PID_d_register` | `src/artisanlib/main.py:18555-18557` | Used by `setPID()` | External PID tuning writes |
| `PID_ON_action` / `PID_OFF_action` | `src/artisanlib/main.py:18558-18559` | Executed through `eventaction(15, ...)` on PID ON/OFF | PLC-side controller enable/disable |
| `PIDmultiplier` | `src/artisanlib/main.py:18560` | Scales P/I/D writes in `s7port.setPID()` | PID tuning value conversion |
| `SVmultiplier` | `src/artisanlib/main.py:18561` | Scales setpoint in `s7port.setTarget()` | SV write conversion |
| `SVtype` | `src/artisanlib/main.py:18562` | Selects `writeFloat()` vs `writeInt()` in `setTarget()` | SV write datatype |

## Table 3 — Recommendation for new architecture

| Текущий элемент Artisan | Оставить как идею / переосмыслить / переписать | Почему |
| --- | --- | --- |
| `s7port` as dedicated runtime object | Оставить как идею | Полезно иметь единый owner connection/cache/mapping state |
| `updateActiveRegisters()` + block polling | Оставить как идею | Хороший reusable concept для efficient PLC polling |
| `area/db_nr/start/type/mode/div` config vocabulary | Оставить как идею | Хороший минимальный контракт для channel mapping |
| `processChannelData()` boundary | Оставить как идею | Четко отделяет raw PLC values от operator-facing values |
| External PID register support | Переосмыслить | Полезно как capability, но не стоит смешивать с общим device transport |
| `self.s7.*` as parallel arrays | Переосмыслить | Лучше structured channel definitions с явными типами |
| `S7`, `S7_34`, `S7_56`, ... device families | Переписать | Это special-case expansion вместо cleaner channel grouping abstraction |
| Direct UI calls from backend | Переписать | Backend должен выдавать domain events/errors, не писать в UI напрямую |
| String `S7 Command` DSL with `eval()` | Переписать | Плохая типизация, безопасность и тестируемость |
| Reconnect embedded in every call | Переосмыслить | Лучше отдельный connection supervisor/state machine |

## Open questions

1. Как snap7 timeout/retry behavior настроен ниже уровня Artisan.
   В коде Artisan явной настройки таймаутов для S7 не видно; чтобы доказать это строго, нужно отдельно просмотреть поведение `python-snap7`/`snap7.client.Client`.

2. Насколько широко используются S7 writes вне event/PID paths.
   В этом разборе подтверждены generic command path и external PID path; для полной картины можно отдельно проверить все action strings в `.aset` для S7-based machines.

3. Нужен ли в новом продукте exact compatibility с pair-based device IDs Artisan.
   По коду видно, что Artisan строит S7 device families через `79/80/81/82/110/151`, но это, вероятно, artifact внутренней device registry, а не обязательное свойство протокола. Для строгого доказательства надо посмотреть, нет ли еще зависимостей на эти IDs в других UI/export местах.
