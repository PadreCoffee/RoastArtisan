# Device Scanning and Discovery Tools in Artisan

## Executive summary

Artisan has several discovery-oriented features, but they are fragmented and protocol-specific rather than organized as a standalone engineering toolkit.

- Serial transport discovery exists as port enumeration in `src/artisanlib/dialogs.py` via `PortComboBox.updateMenu()`, which calls `serial.tools.list_ports.comports()` and feeds `ArtisanPortsDialog` for manual port selection.
- Modbus has the strongest built-in engineering probe: `scanModbusDlg` in `src/artisanlib/ports.py` manually scans register ranges using `ApplicationWindow.modbus.peekSingleRegister()` with function code 3 or 4. This is a register scan, not protocol autodetection.
- S7 has a comparable scan dialog: `scanS7Dlg` in `src/artisanlib/ports.py` iterates address ranges and reads `Int` or `Float` values through `ApplicationWindow.s7.peekInt()` / `peekFloat()`. This is an address/value scan, not PLC model discovery.
- BLE device discovery exists for supported scales only. `devices.py` triggers `ScaleManager.scan_scale{1,2}_signal`, `scale.py` routes to model-specific `Scale.scan()`, and `acaia.py` filters discovered BLE advertisements by known name prefixes after `ble_port.py:ClientBLE.scan()` runs `BleakScanner.discover(...)`.
- I did not find a generic TCP scanner, IP range discovery, Modbus device-ID sweep dialog, generic live raw inspector, or a protocol-agnostic “unknown device engineering mode”. This conclusion is based on traced UI entry points in `ports.py` and `devices.py`, plus repository-wide searches for scan/probe/test/inspector-related code. Confidence is moderate, because absence is inferred from code search rather than a formal feature manifest.

The main architectural pattern is consistent across these tools: UI dialogs/widgets in `ports.py`, `devices.py`, and `dialogs.py` collect current transport settings from `ApplicationWindow` state, invoke low-level backend methods on `aw.modbus`, `aw.s7`, or BLE scale objects, and display results directly in UI widgets. That makes the ideas reusable, but the implementation is tightly coupled to the main application object and current settings state.

## Existing scanning/discovery tools

### 1. Serial port scanning

The serial discovery path is implemented in `src/artisanlib/dialogs.py`.

- `PortComboBox.__init__()` initializes a dynamic list of ports.
- `PortComboBox.updateMenu()` calls `serial.tools.list_ports.comports()` and converts the result into `(device, product, hwid)` tuples.
- On macOS, `updateMenu()` filters known Bluetooth pseudo-ports before populating the combo box.
- `ArtisanPortsDialog` wraps `PortComboBox` into the modal port selection dialog.

Relevant chain:

1. `ApplicationWindow.openMachineSettings()` in `src/artisanlib/main.py:5857+` loads a machine preset with `loadSettings(..., machine=True, reload=False)`.
2. If the resulting device requires a serial or Modbus-serial connection, `openMachineSettings()` creates `ArtisanPortsDialog(...)` and reads the selected port via `commPort_dlg.getSelection()`.
3. The selected port is written into `self.ser.comport` or `self.modbus.comport`.

This is transport discovery only. It answers “which serial ports exist” but does not probe protocol identity, registers, or values.

### 2. Modbus scan dialog

The Modbus engineering scan is implemented in `src/artisanlib/ports.py` as `scanModbusDlg`.

- `PortsDlg.__init__()` creates a `Scan` button with tooltip `Scan MODBUS` (`ports.py:758-759`).
- Clicking it calls `PortsDlg.scanModbus()` (`ports.py:1568-1578`).
- `scanModbus()` copies the current UI transport fields into the dialog object:
  - `port`
  - `baudrate`
  - `bytesize`
  - `stopbits`
  - `parity`
  - `timeout`
  - `mtype`
  - `mhost`
  - `mport`
- `scanModbusDlg.start_pressed()` temporarily overwrites `self.aw.modbus.*` with those values, acquires `self.aw.modbus.COMsemaphore`, iterates a register range, and reads each register using:
  - `self.aw.modbus.peekSingleRegister(self.deviceID, register, code=4)`
  - `self.aw.modbus.peekSingleRegister(self.deviceID, register, code=3)`
- Results are appended to a `QTextEdit` as HTML (`Register,Value` lines).
- At the end the dialog calls `self.aw.modbus.disconnect()` and restores the original `aw.modbus` transport settings.

This is a real register scan and a genuine discovery tool, but it is scoped to a single user-specified Modbus `deviceID` and register range. It does not autodetect device IDs, decode typed values automatically, or persist discovered mappings directly.

Low-level backend path:

1. `scanModbusDlg.start_pressed()` in `ports.py`.
2. `modbusport.peekSingleRegister()` in `src/artisanlib/modbusport.py:911+`.
3. `ModbusPort.connect()` and `read_async()` / `invalidResult()` in `modbusport.py`.
4. Result returned to the dialog and rendered immediately in `modbusEdit`.

### 3. S7 scan dialog

The S7 engineering scan is implemented in `src/artisanlib/ports.py` as `scanS7Dlg`.

- `PortsDlg.__init__()` creates a `Scan` button with tooltip `Scan S7` (`ports.py:946-947`).
- Clicking it calls `PortsDlg.scanS7()` (`ports.py:1559-1565`).
- `scanS7()` seeds the dialog from current UI state:
  - `shost`
  - `sport`
  - `srack`
  - `sslot`
- `scanS7Dlg` lets the user choose:
  - area (`PE`, `PA`, `MK`, `CT`, `TM`, `DB`)
  - `DB#`
  - start range
  - `Int` or `Float` interpretation
- `scanS7Dlg.start_pressed()` temporarily writes those connection parameters into `self.aw.s7.*`, acquires `self.aw.s7.COMsemaphore`, iterates addresses, and reads values using:
  - `self.aw.s7.peekFloat(area, DBnr, register)` when `Float`
  - `self.aw.s7.peekInt(area, DBnr, register)` when `Int`
- Results are appended to a `QTextEdit` as `Start: Value`.
- At the end it calls `self.aw.s7.disconnect()` and restores the original `aw.s7` connection settings.

Low-level backend path:

1. `scanS7Dlg.start_pressed()` in `ports.py`.
2. `S7Port.peekFloat()` / `peekInt()` in `src/artisanlib/s7port.py:566+` and `659+`.
3. `S7Port.connect()` in `s7port.py:197+`.
4. `plc.read_area(...)` in `s7port.py`.
5. Converted value is returned to the dialog and rendered in `S7Edit`.

This is an address/value inspector for known S7 transport settings. It does not infer PLC layout automatically.

### 4. BLE scale discovery

BLE discovery exists, but only in the scale subsystem.

User-facing path:

1. `devices.py` exposes scan buttons for `scale1` and `scale2` (`scanScale1()` / `scanScale2()`).
2. Those methods emit `self.aw.scale_manager.scan_scale1_signal.emit(self.aw.scale1_model)` or the scale2 variant.
3. `ScaleManager.scan_scale1_slot()` / `scan_scale2_slot()` in `src/artisanlib/scale.py` instantiate the selected scale model and call `scale.scan()`.
4. For Acaia, `Acaia.scan()` in `src/artisanlib/acaia.py:988+` calls `self.acaia.scan()`.
5. `ClientBLE.scan()` in `src/artisanlib/ble_port.py:431+` runs `BleakScanner.discover(timeout=..., return_adv=True)`.
6. `Acaia.scan()` filters the discovered BLE advertisements against `ACAIA_SCALE_NAMES` and emits `scanned_signal`.
7. `devices.py:scale1_scanned()` / `scale2_scanned()` populates the combo box with discovered devices.

This is actual BLE discovery, but it is not a generic roaster discovery mode. It is bound to supported scale models and a known name-filtering scheme.

## Manual register/address inspection capabilities

### Modbus

Artisan has two separate manual Modbus inspection paths.

#### A. Scan dialog

The first path is the `scanModbusDlg` described above. It can read raw 16-bit register values over function code 3 or 4 across a user-defined range. It works without a complete machine preset as long as the user can manually enter valid Modbus transport settings in the Ports UI.

Limitations visible in code:

- It scans only one `deviceID` at a time (`scanModbusDlg.deviceID`).
- It reads one register at a time via `peekSingleRegister()`.
- It shows only raw integer values in the text box.
- It does not decode floats, signed values, endianness variants, or structured mappings in the scan dialog itself.

#### B. Event-action command DSL

The second path is `ApplicationWindow.eventaction()` in `src/artisanlib/main.py`. The `action == 4` branch handles “MODBUS Command” strings. The code around `main.py:8675-9275` supports explicit low-level commands such as:

- `read(s,r)`
- `readSigned(s,r)`
- `readBCD(s,r)`
- `read32(s,r)`
- `read32Signed(s,r)`
- `read32BCD(s,r)`
- `readFloat(s,r)`
- `write(...)`
- `writem(...)`
- `writeBCD(...)`
- `writeWord(...)`
- `writeLong(...)`
- `writeSingle(...)`
- `wcoils(...)`
- `wcoil(...)`

These map to `modbusport.py` backend calls like `readSingleRegister()`, `readFloat()`, `readInt32()`, `writeSingleRegister()`, `writeRegisters()`, `writeCoils()`, and `writeCoil()`.

This means Artisan can manually test reads and writes against arbitrary Modbus addresses, but not through a dedicated engineering inspector. The path is embedded in the UI action system and uses command strings interpreted by `eventaction()`.

### S7

S7 likewise has two manual inspection paths.

#### A. Scan dialog

`scanS7Dlg` gives direct address-range reads over:

- selected area
- selected DB number
- selected start range
- selected type (`Int` or `Float`)

It is suitable for exploratory reads of PLC memory locations.

Limitations visible in code:

- Only `Int` and `Float` are exposed in the dialog UI.
- The scan increments by `2` bytes for `Int` or `4` bytes for `Float`.
- There is no bool scan mode in the dialog.
- Results are shown as plain formatted text and are not mapped to channels automatically.

#### B. Event-action command DSL

The `action == 15` branch of `ApplicationWindow.eventaction()` in `src/artisanlib/main.py:10029+` exposes low-level S7 commands:

- `getDBbool(<dbnumber>,<start>,<index>)`
- `getDBint(<dbnumber>,<start>)`
- `getDBfloat(<dbnumber>,<start>)`
- `setDBbool(<dbnumber>,<start>,<index>,<value>)`
- `setDBint(<dbnumber>,<start>,<value>)`
- `msetDBint(<dbnumber>,<start>,andMask,orMask,value)`
- `setDBfloat(<dbnumber>,<start>,<value>)`

Those calls route into:

- `s7port.readBool()`
- `s7port.readInt()`
- `s7port.readFloat()`
- `s7port.writeBool()`
- `s7port.writeInt()`
- `s7port.maskWriteInt()`
- `s7port.writeFloat()`

As with Modbus, this gives manual low-level access, but not via a standalone inspector window.

### Serial/raw transport inspection

I found serial-port enumeration but I did not find a generic serial monitor or raw byte inspector UI in the traced code paths. `PortComboBox` only lists ports, and the discovery/reporting mechanisms I found for live reads target Modbus, S7, and BLE scale scanning. Confidence is moderate.

## Unknown-device onboarding flow

### What exists

Artisan does support manual onboarding of devices without relying entirely on built-in presets, but the flow is distributed across existing configuration dialogs instead of presented as an explicit “unknown device wizard”.

#### Device-family selection

`src/artisanlib/devices.py` contains device selection logic that sets transport defaults and prompts the user toward the next configuration step.

Examples:

- For `meter == 'MODBUS'`, the code sets `self.aw.qmc.device = 29`, initializes serial defaults, and shows the message: `Device set to MODBUS. Now, choose Modbus serial port or IP address`.
- For `meter == 'NONE'`, the code sets a manual/no-device mode and ensures event buttons remain visible.

This shows that the first onboarding decision in Artisan is usually not “discover protocol”, but “pick a device family or manual mode”.

#### Manual transport configuration

The Ports dialog in `src/artisanlib/ports.py` is the next step. It exposes transport-specific editors:

- Modbus serial/TCP settings, including port, baudrate, parity, timeout, type, host, port.
- S7 host/port/rack/slot.
- Per-channel mapping fields for protocol-specific channel definitions.

The scan buttons for Modbus and S7 sit inside these transport configuration tabs, so discovery is embedded inside manual config, not separated from it.

#### Manual validation/probing

The user can then:

- run `Scan MODBUS`
- run `Scan S7`
- or attach action strings that call low-level read/write commands through `eventaction()`

This is the practical path for unknown-device exploration visible in the code.

#### Saving the discovered configuration

There is no separate device-profile serializer for discoveries. The persistence path is generic settings save/load:

1. `ApplicationWindow.saveSettings()` in `src/artisanlib/main.py:25087+` opens `ArtisanSaveFileDialog(..., ext='*.aset')`.
2. It delegates serialization to `closeEventSettings(filename)`, which writes settings groups including `S7` and `Modbus`.
3. `ApplicationWindow.settingsLoad()` reads the same groups from `.aset` using `QSettings(filename, IniFormat)`.

That means a manually discovered setup becomes reusable only by saving the full settings snapshot as `.aset`.

### What does not exist as a dedicated flow

I did not find a single top-level onboarding path that explicitly guides:

1. choose unknown device
2. scan transport
3. inspect raw values
4. bind channels
5. save as reusable device profile

Instead, Artisan spreads those steps across:

- device selection in `devices.py`
- machine preset loading in `main.py`
- transport/mapping tabs in `ports.py`
- action DSLs in `main.py`
- global settings save/load in `main.py`

Confidence is high for this conclusion because the traced UI entry points converge on those files and methods.

## Coupling with protocol backends and UI

The scanning/discovery code is not architecturally isolated.

### Evidence of UI coupling

- `scanModbusDlg` and `scanS7Dlg` live in `src/artisanlib/ports.py`, not in `modbusport.py` or `s7port.py`.
- Both dialogs mutate `self.aw.modbus.*` or `self.aw.s7.*` directly before scanning, then restore the old values afterward.
- Both dialogs use `self.aw.modbus.COMsemaphore` / `self.aw.s7.COMsemaphore`, call backend `disconnect()`, and render results straight into `QTextEdit` widgets.
- The Ports dialog itself initializes form fields directly from runtime objects:
  - `self.modbus_comportEdit = PortComboBox(..., selection=self.aw.modbus.comport)`
  - `self.modbus_hostEdit = QLineEdit(str(self.aw.modbus.host))`
  - `self.s7_hostEdit = QLineEdit(str(self.aw.s7.host))`
  - `self.s7_portEdit = QLineEdit(str(self.aw.s7.port))`

### Evidence of backend reuse boundaries

There is still a usable low-level layer behind the UI:

- `modbusport.py` exposes `peekSingleRegister`, `readSingleRegister`, `readFloat`, `readInt32`, `writeSingleRegister`, `writeRegisters`, `writeCoil`, `writeCoils`, `maskWriteRegister`.
- `s7port.py` exposes `peekInt`, `peekFloat`, `readInt`, `readFloat`, `readBool`, `writeInt`, `writeFloat`, `writeBool`, `maskWriteInt`.
- `ble_port.py` exposes `ClientBLE.scan()` independent of the scale UI.

So the backend primitives are reusable in principle, but the current discovery UX is tightly coupled to `ApplicationWindow` and existing settings/runtime objects.

### Reusability assessment

The part closest to a standalone toolkit is the low-level backend API:

- backend transport/protocol clients in `modbusport.py`, `s7port.py`, `ble_port.py`
- simple register/address scan loops in `scanModbusDlg` and `scanS7Dlg`

The part least reusable as-is is the orchestration:

- UI widgets mutate global runtime state on `aw`
- probe dialogs borrow and restore shared transport state
- results are rendered directly to widgets rather than emitted as structured discovery records
- save/reuse is routed through full-application `.aset` snapshots

## What to carry into the new product

### Keep as product ideas

- A lightweight scan dialog for Modbus register ranges is a good concept. `scanModbusDlg.start_pressed()` shows that even a simple `register -> value` sweep is useful when onboarding unsupported devices.
- The S7 address scanner concept is also strong. `scanS7Dlg` demonstrates a practical minimum feature set: area, DB, start range, type selector, live result list.
- Serial transport enumeration via a reusable widget like `PortComboBox.updateMenu()` is worth keeping.
- BLE discovery separated into backend scan plus UI rendering is also a good pattern. `ble_port.ClientBLE.scan()` and `Acaia.scan()` provide a cleaner separation than the Modbus/S7 scan dialogs.

### Reinterpret before carrying over

- The action-string DSL in `ApplicationWindow.eventaction()` is powerful for ad hoc read/write testing, but it mixes operator actions, UI state, and low-level protocol commands in one large dispatcher. It is useful as a hint that “manual command execution” matters, but not as an architectural model.
- Saving a discovered setup by reusing the full `.aset` settings snapshot works in Artisan, but for a new product it would be better to separate:
  - device transport profile
  - channel mapping profile
  - session/runtime state

### Rewrite rather than copy

- Do not copy the current discovery orchestration pattern where dialogs temporarily overwrite shared runtime objects (`aw.modbus`, `aw.s7`) and then restore them.
- Do not couple engineering discovery mode directly to the roast runtime object graph.
- Do not make “save discovered configuration” depend on a whole-application settings export.

## Open questions

1. I did not find a dedicated generic live raw-value inspector outside Modbus/S7 scan dialogs and the event-action DSLs. If one exists in another optional module or plugin path, it did not surface in the traced entry points.
2. I did not find a generic TCP subnet scan or protocol autodetection feature. Confidence is moderate because this is an absence conclusion from repository search.
3. I did not find a dedicated reusable “user device profile” storage layer separate from full `.aset` settings files. The visible persistence path is the general settings save/load flow in `main.py`.

## Table 1 — Discovery tools map

| Инструмент | Где найден | Что умеет | Для какого протокола/транспорта | Насколько связан с UI/runtime |
| --- | --- | --- | --- | --- |
| `PortComboBox` / `ArtisanPortsDialog` | `src/artisanlib/dialogs.py` | Перечисляет доступные serial ports через `serial.tools.list_ports.comports()` и дает выбрать порт | Serial transport | Сильно связан с UI; только widget/dialog уровень |
| `scanModbusDlg` | `src/artisanlib/ports.py` | Сканирует диапазон регистров и показывает raw values по function code 3/4 | Modbus serial/TCP/UDP в зависимости от текущих transport settings | Сильно связан с `ApplicationWindow` и `aw.modbus` |
| `scanS7Dlg` | `src/artisanlib/ports.py` | Сканирует диапазон адресов S7 по area/DB/start и читает `Int`/`Float` | S7 | Сильно связан с `ApplicationWindow` и `aw.s7` |
| Scale scan buttons | `src/artisanlib/devices.py` | Запускают BLE discovery для поддерживаемых scale models и показывают найденные устройства | BLE scales | Сильно связан с UI, но идет через `ScaleManager` |
| `ScaleManager.scan_scale{1,2}_slot()` | `src/artisanlib/scale.py` | Создает scale object и вызывает `scale.scan()` | BLE scales | Средняя связность; orchestration слой между UI и backend |
| `ClientBLE.scan()` | `src/artisanlib/ble_port.py` | Выполняет BLE discovery через `BleakScanner.discover(...)` | BLE transport | Слабее связан с UI; ближе к reusable backend primitive |
| `eventaction()` Modbus/S7 command paths | `src/artisanlib/main.py` | Дает ручные read/write команды для низкоуровневой проверки адресов и регистров | Modbus, S7 | Очень сильно связан с UI/action system и shared state |

## Table 2 — Unknown-device workflow map

| Шаг | Где реализован | Что делает | Ограничения |
| --- | --- | --- | --- |
| Выбор device family | `src/artisanlib/devices.py` | Переключает `qmc.device`, проставляет transport defaults и показывает next-step message | Это выбор известного family, а не protocol autodetection |
| Загрузка machine preset | `src/artisanlib/main.py:openMachineSettings()` + `loadSettings()` + `settingsLoad()` | Загружает preset `.aset` и частично перезаписывает runtime config | Предполагает существующий preset |
| Ручная transport настройка | `src/artisanlib/ports.py` | Дает редактировать serial / Modbus / S7 connection parameters | Требует ручного знания протокола |
| Modbus register scan | `src/artisanlib/ports.py:scanModbusDlg` | Читает raw register values по диапазону | Нет авто-typed decoding и auto-mapping |
| S7 address scan | `src/artisanlib/ports.py:scanS7Dlg` | Читает raw `Int`/`Float` values по area/DB/start range | Нет bool scan и нет auto-mapping |
| Manual low-level commands | `src/artisanlib/main.py:eventaction()` | Позволяет вручную читать/писать Modbus/S7 адреса через command strings | Не отдельный inspector, а встроенный action DSL |
| Сохранение найденной конфигурации | `src/artisanlib/main.py:saveSettings()` | Сохраняет текущий runtime/settings snapshot в `.aset` | Нет отдельного reusable device profile формата |

## Table 3 — Recommendation for new architecture

| Элемент Artisan | Оставить как идею / переосмыслить / переписать | Почему |
| --- | --- | --- |
| Serial port enumeration (`PortComboBox.updateMenu()`) | Оставить как идею | Это полезный минимальный transport-discovery primitive |
| Modbus register scan dialog | Оставить как идею | Хороший базовый engineering tool для unknown-device onboarding |
| S7 address scan dialog | Оставить как идею | Практичный минимальный PLC probing workflow |
| BLE scan backend (`ClientBLE.scan()`) | Оставить как идею | Это уже ближе к чистому backend abstraction |
| Scale discovery flow through `ScaleManager` | Переосмыслить | Идея orchestration полезна, но сейчас ограничена scale-specific моделями |
| `eventaction()` low-level command DSL | Переосмыслить | Покрывает реальную инженерную потребность, но смешивает UI actions, scripting и device I/O |
| Scan dialogs mutating shared `aw.modbus` / `aw.s7` | Переписать | Discovery не должен временно переписывать глобальный runtime transport state |
| Save discovered config via full `.aset` settings snapshot | Переписать | Для нового продукта лучше отдельный device profile / mapping profile compatibility layer |
