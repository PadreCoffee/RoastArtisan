# Modbus Device Architecture in Artisan

## Executive summary

Artisan реализует Modbus не как изолированный transport adapter и не как чистый protocol layer, а как смешанный слой вокруг объекта `ApplicationWindow.modbus`, созданного в `src/artisanlib/main.py:1777`. Основной backend-класс находится в `src/artisanlib/modbusport.py` и одновременно держит transport/session state, per-channel mapping, batching optimizer, low-level read/write API и PID-related helpers. UI/settings входят в этот runtime через `ports.py` и `main.py`: диалог настроек заполняется из `self.aw.modbus.*` в `src/artisanlib/ports.py:475-590`, а после подтверждения копирует значения обратно в `self.modbus.*` в `src/artisanlib/main.py:24646-24767`. Загрузка `.aset`/QSettings в runtime происходит в `settingsLoad()` через группу `Modbus` в `src/artisanlib/main.py:18570-18621`; сохранение обратно идет через тот же набор полей в `src/artisanlib/main.py:20532-20570`.

Sampling не читает Modbus напрямую из UI. Вместо этого `comm.py` использует общий device dispatch table `devicefunctionlist` (`src/artisanlib/comm.py:377-430`), где Modbus занимает device IDs `29`, `33`, `55`, `109`, `150`. Основной bridge в roast runtime проходит по цепочке `devicefunctionlist -> comm.MODBUS()/MODBUSread() -> modbusport.read*() -> processChannelData() -> extraMODBUStemps / returned ET-BT tuple` (`src/artisanlib/comm.py:1635-1651`, `3066-3184`). Это означает, что Modbus логически встроен в общий sampling pipeline Artisan, но его configuration/mapping state живет не в отдельной domain model, а внутри `self.modbus` и частично в `ApplicationWindow`.

По коду Modbus backend поддерживает и чтение, и запись. Чтение каналов использует per-channel arrays `inputDeviceIds/inputRegisters/inputCodes/inputDivs/inputModes/...` в `modbusport`, а запись идет либо через прямые helper-методы `writeCoil/writeCoils/writeSingleRegister/writeRegisters/writeWord/writeBCD/writeLong/maskWriteRegister` (`src/artisanlib/modbusport.py:525-760`), либо через строковый action DSL в `ApplicationWindow.eventaction()` для action type `4` (`src/artisanlib/main.py:9024-9275`). Из-за этого граница между operator action и low-level device write существует, но она слабая: верхний уровень часто формирует строки команд, которые потом `eval()`-ятся в UI/application layer.

Уровень уверенности высокий по цепочке `.aset -> self.modbus.* -> comm.MODBUSread() -> runtime sampling` и по low-level write API; средний по тому, как отдельные machine presets реально используют всю ширину write DSL, потому что в рамках этого разбора исследовался код Artisan и набор preset examples, а не все пользовательские `.aset`.

## Where Modbus is implemented

### Main implementation files

- `src/artisanlib/modbusport.py`
  - Основной backend-класс `modbusport`.
  - Держит transport type (`type`), serial/TCP/UDP parameters, connection objects `_asyncLoopThread` и `_client`, optimizer cache, read/write methods и PID helpers.
- `src/artisanlib/main.py`
  - Создает `self.modbus` в `ApplicationWindow.__init__()` (`1777`).
  - Загружает группу `Modbus` из QSettings/`.aset` (`18570-18621`).
  - Сохраняет ее обратно (`20532-20570`).
  - Копирует значения из UI-диалога в `self.modbus.*` внутри `setcommport()` (`24646-24767`).
  - Маршрутизирует action type `4` как `MODBUS Command` через `eventaction()` (`9024-9275`).
- `src/artisanlib/ports.py`
  - UI-редактор Modbus settings: transport, decode, per-channel mapping, PID settings (`475-590`, `836-916`).
  - `scanModbus()` передает текущие UI values в scan dialog (`1568-1578`).
- `src/artisanlib/comm.py`
  - Подключает Modbus в общий sampling dispatch table (`377-430`).
  - Содержит bridge-методы `MODBUS`, `MODBUS_34`, `MODBUS_56`, `MODBUS_78`, `MODBUS_910`, `MODBUSread`, `processChannelData` (`1635-1651`, `3066-3184`).
- `src/artisanlib/pid_control.py`
  - Использует Modbus как внешний PID backend через `externalPIDControl()`, `pidOn()`, `pidOff()`, `setSV()`, `confPID()` (`1279-1288`, `1478-1545`, `1722-1742`, `1872-1885`).
- `src/artisanlib/canvas.py`
  - Использует Modbus-specific runtime metadata в UI/runtime formatting, например `intChannel()` (`4445-4463`).

### What kind of layer it is

По коду это смесь нескольких слоев:

- transport/session layer:
  - `connect()`, `connect_async()`, `disconnect()`, `_client`, `_asyncLoopThread` в `modbusport.py:261-366`
- protocol read/write layer:
  - `read_async()`, `read_registers()`, `readSingleRegister()`, `readFloat()`, `writeSingleRegister()`, `writeCoil()` и др. в `modbusport.py:525-1120`
- mapping/config layer:
  - `inputDeviceIds`, `inputRegisters`, `inputFloats`, `inputCodes`, `inputDivs`, `inputModes`, `wordorderLittle` в `modbusport.py:86-157`
- batch polling/cache layer:
  - `updateActiveRegisters()`, `readActiveRegisters()`, `read_active_registers_async()`, `readingsCache` в `modbusport.py:376-520`
- application/runtime bridge:
  - `comm.MODBUSread()` и `processChannelData()` в `comm.py:3066-3184`
- operator action integration:
  - `eventaction()` action type `4` в `main.py:9024-9275`

Строго по коду это не отдельный device driver family per roaster и не просто общий Modbus transport adapter. Это общий Modbus backend для разных machine presets, но он встроен в application layer настолько плотно, что фактически является mixed integration layer.

## Runtime flow from `.aset` to connection

### Call chain from config to runtime

1. Preset or settings file содержит группу `[Modbus]`.
   - Примеры: `src/includes/Machines/BlueKing/BK.aset:11-95`, `src/includes/Machines/Coffed/SR5_automatic.aset:...`, `src/includes/Machines/iRm Series/Mitsubishi_PLC.aset:92-176`.
2. `ApplicationWindow.settingsLoad()` читает группу `Modbus`.
   - `src/artisanlib/main.py:18570-18621`
   - Заполняет `self.modbus.comport/baudrate/.../type/host/port` и per-channel arrays `input{i}*`.
3. `ApplicationWindow.__init__()` уже создал объект backend.
   - `self.modbus = modbusport(self)` в `src/artisanlib/main.py:1777`
4. UI device settings dialog инициализируется текущими значениями из `self.aw.modbus`.
   - `src/artisanlib/ports.py:475-590`
5. После подтверждения диалога `setcommport()` копирует UI values назад в `self.modbus.*`.
   - `src/artisanlib/main.py:24646-24767`
6. Sampling loop выбирает Modbus как main/extra device через `devicefunctionlist`.
   - `src/artisanlib/comm.py:377-430`
7. `comm.MODBUSread()` вызывает `self.aw.modbus.readActiveRegisters()` и затем per-channel `read*()`.
   - `src/artisanlib/comm.py:3116-3184`
8. `modbusport.readActiveRegisters()` при необходимости вызывает `connect()`, а тот создает/использует `_asyncLoopThread` и `_client`.
   - `src/artisanlib/modbusport.py:291-366`, `440-520`

### How `.aset` fields become runtime state

Загрузка идет не через отдельный parser для `.aset` именно Modbus, а через общий `QSettings` path. В `main.py:18570-18621` значения из группы `Modbus` читаются напрямую в поля `self.modbus`. Это важная архитектурная деталь: runtime config объекта `modbusport` является практически прямым отражением persisted settings schema.

### Table 1 - Modbus runtime map

| Компонент | Где найден | Роль | Входы | Выходы | Насколько связан с UI |
|---|---|---|---|---|---|
| `ApplicationWindow.modbus` | `src/artisanlib/main.py:1777` | Корневой runtime holder для Modbus | `ApplicationWindow`, settings, UI dialog | backend state для sampling/PID/actions | Высоко: принадлежит `ApplicationWindow` |
| `modbusport` | `src/artisanlib/modbusport.py:79-157` | Смешанный backend: transport + protocol + mapping + cache + PID helpers | `.aset`/QSettings values, action commands, sampling requests | register reads, writes, cache, status messages | Высоко: вызывает `aw.sendmessage`, `aw.qmc.adderror`, `aw.addserial` |
| Modbus settings UI | `src/artisanlib/ports.py:475-590` | UI entry point для transport/mapping/PID | `self.aw.modbus.*` | виджеты и пользовательские edits | Полностью UI |
| `setcommport()` Modbus branch | `src/artisanlib/main.py:24646-24767` | Переносит UI state в runtime backend | значения диалога | мутация `self.modbus.*` | Очень высоко |
| Modbus settings loader | `src/artisanlib/main.py:18570-18621` | Читает persisted config | QSettings group `Modbus` | мутация `self.modbus.*` | Средне: app settings layer |
| Modbus settings saver | `src/artisanlib/main.py:20532-20570` | Сохраняет runtime config обратно | `self.modbus.*` | QSettings group `Modbus` | Средне |
| `devicefunctionlist` | `src/artisanlib/comm.py:377-430` | Включает Modbus в общий sampling dispatch | `qmc.device` / extra device IDs | вызов `MODBUS*()` | Низко-средне |
| `MODBUSread()` | `src/artisanlib/comm.py:3116-3184` | Bridge между backend и roast runtime channels | `self.aw.modbus.*`, polling tick | ET/BT pair, `extraMODBUStemps` | Средне |
| `eventaction()` action 4 | `src/artisanlib/main.py:9024-9275` | Operator action -> low-level Modbus command DSL | action string, button state, `lastReadResult` | writes/reads against Modbus backend | Очень высоко |
| external PID bridge | `src/artisanlib/pid_control.py:1279-1288`, `1478-1545`, `1722-1742`, `1872-1885` | Использует Modbus как внешний PID backend | PID UI/actions | `setTarget`, `setPID`, `PID_ON/OFF_action` | Очень высоко |

### Table 2 - Mapping from config to runtime

| Поле конфигурации | Где читается | Как используется | На что влияет в runtime |
|---|---|---|---|
| `comport`, `baudrate`, `bytesize`, `stopbits`, `parity`, `timeout` | `src/artisanlib/main.py:18571-18576` | Копируются в `self.modbus.*` | Serial RTU/ASCII client creation в `connect_async()` |
| `modbus_serial_connect_delay`, `serial_readRetries` | `src/artisanlib/main.py:18577-18578` | Копируются в `self.modbus.*` | serial connect wait и pymodbus retry count |
| `IP_timeout`, `IP_retries` | `src/artisanlib/main.py:18579-18580` | Копируются в `self.modbus.*` | TCP/UDP timeout and retries в `connect_async()` |
| `type` | `src/artisanlib/main.py:18618` | integer enum в `self.modbus.type` | Ветвление Serial RTU / ASCII / Binary / TCP / UDP |
| `host`, `port` | `src/artisanlib/main.py:18619-18620` | Копируются в runtime | TCP/UDP endpoint |
| `input{i}deviceId` | `src/artisanlib/main.py:18581-18588` | slave/device id per channel | Активность канала и адресация Modbus device |
| `input{i}register` | `src/artisanlib/main.py:18589` | register per channel | low-level read/write address |
| `input{i}code` | `src/artisanlib/main.py:18592` | function code per channel | coils/discrete/holding/input register read path |
| `input{i}float`, `input{i}bcd`, `input{i}FloatsAsInt`, `input{i}BCDsAsInt`, `input{i}Signed` | `src/artisanlib/main.py:18590-18596` | decode flags per channel | выбор `readFloat` / `readInt32` / `readBCD` / `readBCDint` / `readSingleRegister` |
| `input{i}div`, `input{i}mode` | `src/artisanlib/main.py:18593-18594` | scaling and unit mode | `processChannelData()` divider and C/F conversion |
| `wordorderLittle` | `src/artisanlib/main.py:18597` | bool flag | FLOAT32/INT32 encode-decode word order |
| `optimizer`, `fetch_max_blocks` | `src/artisanlib/main.py:18598-18599` | bool flags | batched reads and sequence strategy |
| `PID_device_ID`, `PID_*_register` | `src/artisanlib/main.py:18606-18614` | PID target/tuning mapping | `setTarget()`, `setPID()`, external PID detection |
| `PID_ON_action`, `PID_OFF_action` | `src/artisanlib/main.py:18615-18616` | action strings | `pidOn()` / `pidOff()` -> `eventaction(4, ...)` |
| `PIDmultiplier`, `SVmultiplier`, `SVwriteLong`, `SVwriteFloat` | `src/artisanlib/main.py:18600-18603` | write conversion config | how PID values and SV are encoded on writes |

## Address/value mapping model

### How channel mapping is represented

В Modbus mapping нет отдельного object-per-channel класса. Вместо этого `modbusport.__init__()` создает набор параллельных массивов длины `channels = 10`:

- `inputDeviceIds`
- `inputRegisters`
- `inputFloats`
- `inputBCDs`
- `inputFloatsAsInt`
- `inputBCDsAsInt`
- `inputSigned`
- `inputCodes`
- `inputDivs`
- `inputModes`

Источник: `src/artisanlib/modbusport.py:108-133`.

Это означает, что единая модель mapping существует, но реализована как parallel arrays, а не как явная typed structure. Для reverse engineering это важно: логика канала определяется не одним объектом, а согласованным набором индексов в нескольких массивах.

### Where addresses, types, and decode rules are interpreted

- UI decode options задаются в `ports.py`:
  - `modbus_function_codes = ['1','2','3','4']`
  - `modbus_modes = ['', 'C', 'F']`
  - `modbus_divs = ['', '1/10', '1/100']`
  - `modbus_decode = ['uInt16', 'uInt32', 'sInt16', 'sInt32', 'BCD16', 'BCD32', 'Float32']`
  - `src/artisanlib/ports.py:475-478`
- Преобразование UI decode choice обратно в runtime flags делается в `setcommport()`.
  - `src/artisanlib/main.py:24703-24741`
- Интерпретация register/function/decode flags при чтении делается в `comm.MODBUSread()`.
  - `src/artisanlib/comm.py:3134-3182`
- Low-level decoding выполняется в `modbusport.read*()` и conversion helpers.
  - `readFloat`, `readInt32`, `readBCD`, `readBCDint`, `readSingleRegister` в `src/artisanlib/modbusport.py:826-1087`
  - `word_order()`, `convert_*_from_registers()` в `src/artisanlib/modbusport.py:186-246`

### Raw machine values vs operator-facing values

Разделение между raw machine values и operator-facing values проходит не в `modbusport`, а в `comm.processChannelData()`.

- `modbusport.read*()` возвращают raw numeric value после decode/sign/endianness/BCD conversion.
- `comm.processChannelData()` затем применяет:
  - divider `1/10`, `1/100`
  - temperature unit conversion between C and F depending on `aw.qmc.mode`
  - `src/artisanlib/comm.py:3066-3082`
- `comm.MODBUSread()` вызывает `processChannelData()` для каждого канала перед записью в `extraMODBUStemps`.
  - `src/artisanlib/comm.py:3182-3184`

То есть raw/register-domain и operator-facing/value-domain разделены, но не отдельными моделями. Разделение выражено как последовательность вызовов `read*()` -> `processChannelData()`.

### How channels enter roast runtime and profile

Modbus сам не пишет в профиль напрямую. Он только возвращает значения в общий sampling flow:

- `comm.MODBUS()` возвращает `(tx, t2, t1)` для main device (`src/artisanlib/comm.py:1635-1639`)
- дополнительные каналы идут через `MODBUS_34`, `MODBUS_56`, `MODBUS_78`, `MODBUS_910` (`1641-1651`)
- значения сохраняются в `aw.extraMODBUStemps` (`3184`)
- `canvas.py` затем использует общий sampling pipeline `self.aw.ser.devicefunctionlist[self.aw.qmc.device]()` и extra device functions (`src/artisanlib/canvas.py:19597`, `19612` по rg)

В рамках этого разбора можно строго утверждать: Modbus channels попадают в roast runtime через generic devicefunction dispatch, а не через отдельный persisted profile serializer. Как именно они затем сериализуются в `.alog`, находится уже в общем profile pipeline, а не в Modbus-specific коде.

### Required config fields

Строго обязательные поля по коду зависят от транспортного режима и активного канала:

- для serial: `comport`, `baudrate`, `bytesize`, `parity`, `stopbits`, `timeout`
- для TCP/UDP: `host`, `port`, `type`
- для активного канала:
  - `input{i}deviceId != 0`
  - `input{i}register`
  - `input{i}code`
  - decode defaults могут не быть заданы, потому что constructor already defaults to `uInt16`, code `3`, divider `0`, mode `'C'`

Это следует из:

- channel считается активным только если `inputDeviceIds[i] != 0` в `updateActiveRegisters()` (`src/artisanlib/modbusport.py:380-391`) и `comm.MODBUSread()` (`src/artisanlib/comm.py:3133-3135`)
- client branch определяется `self.type` в `connect_async()` (`src/artisanlib/modbusport.py:299-345`)

## Polling and reconnect model

### Who opens the connection

Соединение открывает `modbusport.connect()`, который поднимает `AsyncLoopThread` и затем synchronously waits for `connect_async()`.

- `src/artisanlib/modbusport.py:291-295`

`connect_async()` создает конкретный pymodbus async client в зависимости от `self.type`:

- `1` -> `AsyncModbusSerialClient(... framer=ASCII ...)`
- `2` -> Serial Binary branch with `pass`
- `3` -> `AsyncModbusTcpClient`
- `4` -> `AsyncModbusUdpClient`
- else -> `AsyncModbusSerialClient(... framer=RTU ...)`

Источник: `src/artisanlib/modbusport.py:297-345`.

### Where connection state lives

Connection state хранится внутри `modbusport`:

- `_client`
- `_asyncLoopThread`
- `commError`
- `readingsCache`
- `activeRegisterSequences`

Определение state видно в `__slots__` и `__init__()`:

- `src/artisanlib/modbusport.py:86-157`

Признак соединения:

- `isConnected()` не попал в текущие excerpts, но по ранее собранным line refs находится рядом с connect/disconnect и проверяет `_client is not None and _client.connected`.
- Уверенность высокая: это подтверждалось предыдущим чтением файла и поведением `connect_async()/disconnectOnError()`.

### How polling works

Polling двухслойный:

1. optimizer layer
   - `readActiveRegisters()` вызывается на sampling tick (`comm.MODBUSread()`, `src/artisanlib/comm.py:3119-3124`)
   - `updateActiveRegisters()` строит последовательности активных регистров по `(code, device_id)` и учитывает, что 32-bit reads занимают два регистра (`src/artisanlib/modbusport.py:376-399`)
   - `read_active_registers_async()` читает батчами только codes `3` и `4` и кладет значения в `readingsCache` (`460-520`)
2. per-channel extraction layer
   - `comm.MODBUSread()` для каждого активного канала вызывает конкретный `read*()`
   - `read_registers()` пытается ответить из cache, а при необходимости делает индивидуальный запрос (`src/artisanlib/modbusport.py:791-822`)

Таким образом, polling model состоит из background-like prefetch per sampling tick + per-channel decode extraction, но все это все еще выполняется внутри основного sampling call path, а не в отдельном long-running polling service.

### Timeouts, retries, reconnect, errors

- timeout для клиентов ограничивается половиной sampling delay:
  - serial uses `min((self.aw.qmc.delay/2000), self.timeout)`
  - TCP/UDP uses `min((self.aw.qmc.delay/2000), self.IP_timeout)`
  - `src/artisanlib/modbusport.py:299-345`
- reconnect strategy:
  - на read/write путь вызывается `connect()` перед операцией
  - `disconnectOnError()` разрывает соединение, если `disconnect_on_error` и `commError > acceptable_errors` или `not isConnected()`
  - `src/artisanlib/modbusport.py:274-289`
- error counter:
  - `commError` increment происходит после communication errors, когда ошибка требует disconnect (`read_active_registers_async()` и `read*()` except branches)
  - `clearCommError()` сбрасывает счетчик и пишет `Modbus Communication Resumed`
  - `src/artisanlib/modbusport.py:274-279`, `460-520`, `826-1087`

Это не автономный reconnect daemon. Скорее это lazy reconnect on next operation: ошибка может вызвать `disconnect()`, а следующая read/write операция снова вызовет `connect()`.

### RTU vs TCP distinction

Различие RTU/ASCII/TCP/UDP живет в `modbusport.connect_async()` и partly в UI:

- UI transport type combo: `['Serial RTU', 'Serial ASCII', 'Serial Binary', 'TCP', 'UDP']` (`src/artisanlib/ports.py:557-569`)
- runtime branch by `self.type` (`src/artisanlib/modbusport.py:299-345`)

Отдельного transport abstraction layer поверх этого нет. Вся ветвистость сосредоточена в одном backend классе.

## Outgoing write path

### Low-level write API

`modbusport` поддерживает полноценную запись:

- coils:
  - `writeCoils()` function 15
  - `writeCoil()` function 5
- holding register writes:
  - `writeSingleRegister()` function 6
  - `writeRegisters()` function 16
  - `maskWriteRegister()` function 22
  - `localMaskWriteRegister()` emulation via function 6
- converted multi-register payloads:
  - `writeWord()` for FLOAT32
  - `writeBCD()`
  - `writeLong()` for INT32

Источник: `src/artisanlib/modbusport.py:525-760`.

Следовательно, backend не read-only. По коду это полноценный Modbus read/write backend.

### Operator action -> low-level write chain

Основной operator-facing path идет через `ApplicationWindow.eventaction()` action `4`:

- action `4` помечен как `MODBUS Command` (`src/artisanlib/main.py:9024+`)
- command string может содержать последовательность `;`-separated commands
- `_` заменяется на `self.modbus.lastReadResult`
- `$` заменяется на current button state
- поддерживаются команды:
  - `writem(...)`
  - `sleep(...)`
  - `writeBCD(...)`
  - `writeWord(...)`
  - `writeLong(...)`
  - `writeSingle(...)`
  - `write(...)`
  - `mwrite(...)`
  - `wcoils(...)`
  - `wcoil(...)`
  - `read(...)`
  - `readSigned(...)`
  - `readBCD(...)`
  - `read32(...)`
  - `read32Signed(...)`
  - `read32BCD(...)`
  - `readFloat(...)`

Источник: `src/artisanlib/main.py:9024-9275`.

Это важная граница слоев:

- operator action формально отделен как string command
- но low-level device writes формируются не отдельным command object model, а через parsed/eval-ed strings в `main.py`

То есть разделение есть, но архитектурно оно weakly typed и сильно связано с UI/actions.

### PID write path

Есть и более structured write path для external PID:

- `pid_control.externalPIDControl()` считает Modbus external PID активным, если `self.aw.modbus.PID_device_ID != 0`
  - `src/artisanlib/pid_control.py:1279-1288`
- `pidOn()` и `pidOff()` отправляют `PID_ON_action` / `PID_OFF_action` через `eventaction(4, ...)`
  - `src/artisanlib/pid_control.py:1478-1545`
- `setSV()` вызывает `self.aw.modbus.setTarget(sv)`
  - `src/artisanlib/pid_control.py:1722-1742`
- `confPID()` вызывает `self.aw.modbus.setPID(kp,ki,kd)`
  - `src/artisanlib/pid_control.py:1872-1885`
- `setTarget()` и `setPID()` затем конвертируют значения через `SVmultiplier`, `PIDmultiplier`, `SVwriteFloat`, `SVwriteLong`
  - `src/artisanlib/modbusport.py:1090-1117`

Это один из немногих путей, где operator action превращается в low-level write без string DSL.

## Coupling / architectural weaknesses

### Tight coupling actually visible in code

1. `modbusport` зависит от `ApplicationWindow` напрямую.
   - constructor принимает `aw`
   - backend пишет в `aw.sendmessage`, `aw.qmc.adderror`, `aw.addserial`
   - `src/artisanlib/modbusport.py:97`, `261-289`, `460-520`, `525-760`
2. Runtime config и persisted config почти совпадают one-to-one.
   - `main.py:18570-18621` и `20532-20570`
   - это удобно, но привязывает runtime schema к settings schema
3. Channel mapping хранится как parallel arrays.
   - `modbusport.py:108-133`
   - это делает код чувствительным к index discipline и затрудняет unit-level composition
4. Sampling bridge знает Modbus-specific decode flags.
   - `comm.MODBUSread()` читает `inputFloats`, `inputBCDs`, `inputSigned`, `inputDivs`, `inputModes`
   - `src/artisanlib/comm.py:3134-3184`
5. UI branch `canvas.intChannel()` тоже знает Modbus-specific internals.
   - `src/artisanlib/canvas.py:4445-4463`
6. Operator command layer использует string DSL с `eval()`.
   - `src/artisanlib/main.py:9024-9275`
   - это сильная связность с UI/button/event system и слабая типобезопасность

### Logical separation quality

Если разложить по requested axes:

- transport:
  - частично отделен внутри `connect_async()` по `type`
  - но не вынесен в отдельные классы
- protocol:
  - read/write operations сгруппированы в `modbusport`
  - это лучше, чем распыление по UI, но все еще смешано с transport and app concerns
- mapping:
  - представлен явно, но в parallel arrays и partly interpreted in `comm.py`
- device-specific config:
  - в основном приходит из `.aset [Modbus]`
  - presets задают mapping without separate driver classes
- runtime roast state:
  - уже живет вне `modbusport`, в общем sampling/canvas/runtime path
  - это separation существует, но bridge между ними не чистый

Уровень уверенности высокий: эти границы прямо наблюдаются в перечисленных файлах и цепочках вызовов.

## What to carry into the new product

### Reusable concepts

1. Оставить как идею: transport-type enum и единый backend entry point.
   - Основание: `self.type` и `connect_async()` в `src/artisanlib/modbusport.py:297-345`
   - Почему: удобно поддерживать RTU/TCP/UDP под одной интеграцией, если их lifecycle стандартизован.
2. Оставить как идею: per-channel declarative mapping.
   - Основание: `inputDeviceIds/inputRegisters/inputCodes/inputDivs/inputModes/...` (`modbusport.py:108-133`)
   - Почему: machine presets действительно конфигурируют ростеры без device-specific Python code.
3. Оставить как идею: optimizer over active register sequences.
   - Основание: `updateActiveRegisters()` + `read_active_registers_async()` (`376-520`)
   - Почему: это полезный reusable concept для polling efficiency.
4. Оставить как идею: явное разделение raw register decode и operator-facing unit conversion.
   - Основание: `read*()` vs `processChannelData()` (`modbusport.py:826-1087`, `comm.py:3066-3184`)
   - Почему: новый продукт может сохранить этот pipeline, но оформить его как typed stages.
5. Оставить как идею: structured PID helpers `setTarget()` / `setPID()`.
   - Основание: `modbusport.py:1090-1117`
   - Почему: это уже ближе к нормальному application service, чем string action DSL.

### Better redesigned from scratch

1. Переписать: `modbusport` как god-object.
   - Почему: сейчас один класс смешивает transport, protocol, mapping, cache, logging, UI messaging, PID writes.
2. Переписать: parallel arrays в channel mapping.
   - Почему: новый продукт лучше строить вокруг explicit `ChannelBinding` / `RegisterBinding`.
3. Переписать: string-based command DSL с `eval()`.
   - Основание: `main.py:9024-9275`
   - Почему: это legacy coupling к UI/event system и повышенный риск ошибок.
4. Переосмыслить: прямую зависимость backend от UI/state owner.
   - Основание: `aw.sendmessage`, `aw.qmc.adderror`, `aw.addserial`
   - Почему: новый device layer лучше держать testable без `ApplicationWindow`.
5. Переосмыслить: special device IDs `29/33/55/109/150` для групп каналов.
   - Основание: `comm.py:377-430`, `1635-1651`
   - Почему: это historical integration artifact, а не чистая channel grouping model.

### Table 3 - Recommendation for new architecture

| Текущий элемент Artisan | Оставить как идею / переосмыслить / переписать | Почему |
|---|---|---|
| Один общий Modbus backend для RTU/TCP/UDP | Оставить как идею | Полезно иметь один integration family с несколькими transport implementations |
| `connect_async()` branching by transport type | Переосмыслить | Идея верная, но лучше вынести transport implementations в отдельные классы |
| Per-channel configurable mapping из `.aset` | Оставить как идею | Позволяет поддерживать разные ростеры без нового кода |
| Mapping в parallel arrays | Переписать | Слишком хрупко и плохо тестируется |
| Optimizer и batched active register reads | Оставить как идею | Это сильный reusable performance concept |
| `processChannelData()` как post-decode normalization | Оставить как идею | Хорошая граница raw vs operator-facing values |
| Backend calls в `aw.sendmessage/qmc.adderror/addserial` | Переписать | Это прямая UI/state coupling |
| `eventaction()` Modbus command DSL | Переписать | `eval()` и string parsing создают tight coupling и weak typing |
| PID helpers `setTarget()/setPID()` | Оставить как идею | Нормальная application-level abstraction поверх low-level writes |
| Device IDs `29/33/55/109/150` для Modbus channel groups | Переосмыслить | Работает, но выглядит как legacy dispatch encoding |

## Open questions

1. Не удалось строго доказать только по коду, используются ли все ветки action DSL в штатных machine presets или часть осталась legacy.
   - Что проверить дополнительно: поиск по preset/action definitions на `writeWord(`, `mwrite(`, `read32(` и related commands.
   - Уровень уверенности: средний.
2. По коду видно, что Serial Binary branch фактически не поддерживается (`pass` в `connect_async()`), а UI item disabled.
   - Что проверить дополнительно: были ли legacy branches или compatibility expectations вне текущей версии.
   - Уровень уверенности: высокий.
3. Для полного анализа связи Modbus channels с persisted roast profile нужно смотреть общий profile serialization path, а не Modbus-specific код.
   - В этом отчете доказан путь только до runtime sampling/state bridge.
   - Уровень уверенности: высокий.
