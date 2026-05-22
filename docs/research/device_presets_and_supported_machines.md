# Device Presets and Supported Machines in Artisan

## Executive summary

В Artisan built-in machine presets хранятся прежде всего как файловая библиотека `.aset`-шаблонов в `src/includes/Machines`, а не как hardcoded Python tables. Меню выбора машин строится динамически функцией `populateListMenu('Machines', '.aset', ...)` в `src/artisanlib/main.py:5782-5854`, которая обходит `os.walk(os.path.join(getResourcePath(), 'Machines'))`, группирует файлы по каталогам-брендам и создает `QAction` для каждого найденного preset. По состоянию текущего дерева `src/includes/Machines` в проекте есть 88 brand directories и 252 `.aset`-preset files; это подтверждается прямым обходом файловой системы.

Выбор preset в UI ведет не к специальному machine parser, а к вызову общего `loadSettings()` с флагом `machine=True` из `openMachineSettings()` (`src/artisanlib/main.py:5857-5895`). Дальше preset-файл проходит через тот же `settingsLoad()` path, что и обычный settings export/import (`src/artisanlib/main.py:18011-19095`). Из-за этого machine preset фактически является частичным settings snapshot: он может задавать transport/protocol/device ids, channel mappings, slider/button actions, extra devices, machine metadata, energy defaults и другие группы настроек, которые затем попадают прямо в runtime state (`self.qmc`, `self.ser`, `self.modbus`, `self.s7`, `self.ws`, и т.д.).

Граница между preset и user overrides в Artisan слабая, но прослеживаемая. Built-in preset сначала мутирует runtime через `settingsLoad(machine=True)`, а затем `openMachineSettings()` в ряде случаев запрашивает у пользователя host/comport/capacity/heating type и при отмене вручную откатывает часть полей к сохраненным значениям (`src/artisanlib/main.py:5883-6100`). После применения пользователь может дополнительно редактировать те же настройки через обычные UI-диалоги и сохранить их в свой `.aset` через `Help -> Save Settings...` (`src/artisanlib/main.py:25087-25109`). При этом отдельного user machine library, аналогичного `Themes/User`, в исходниках не видно: есть общие пользовательские `.aset`-settings files, но нет отдельного `Machines/User` каталога и нет отдельного “Save Machine Preset” flow.

Уровень уверенности высокий по цепочке `preset selection -> loadSettings(machine=True) -> settingsLoad() -> runtime mutation` и по месту хранения built-in presets. Уровень уверенности средний в вопросе, какая часть секций `.aset` действительно обязательна для каждого конкретного ростера, потому что это зависит от конкретного preset-файла, а не от одного общего schema validator.

## Where supported machines/presets are defined

### Built-in preset storage

Главный источник supported machines/devices в кодовой базе:

- `src/includes/Machines/<Brand>/<Preset>.aset`

Примеры:

- `src/includes/Machines/Probat/G_UG_WebSockets.aset`
- `src/includes/Machines/Coffed/SR5_automatic.aset`
- `src/includes/Machines/iRm Series/Mitsubishi_PLC.aset`

Файлы упаковываются в приложение как ресурсная папка:

- `src/artisan-mac.spec:106` добавляет `includes/Machines` в bundle как `./Machines`
- `src/artisan-win.spec:298-299` создает `TARGET + 'Machines'` и копирует `includes\\Machines`
- `src/build-linux-buster.sh:126-128` копирует `includes/Machines/*` в `dist/Machines`

То есть built-in preset library в продакшн-сборке тоже остается файловой библиотекой, а не компилируется в код.

### How UI discovers supported machines

Меню машин создается динамически:

- `self.machineMenu = QMenu('Machine')` в `src/artisanlib/main.py:2478`
- `QTimer.singleShot(500, self.populateMachineMenu)` в `src/artisanlib/main.py:2481`
- `populateMachineMenu()` вызывает `populateListMenu('Machines', '.aset', self.openMachineSettings, self.machineMenu, addMenu=False)` в `src/artisanlib/main.py:5853-5854`

`populateListMenu()`:

- делает `os.walk(os.path.join(getResourcePath(), resourceName))`
- фильтрует файлы по расширению
- использует имя каталога как group/brand
- кладет в `QAction.data()` кортеж `(full_path, group_name)`
- строит submenu per brand, если в группе больше одного preset

Источник: `src/artisanlib/main.py:5782-5851`.

Отсюда следует:

- список supported machines не hardcoded в Python enum;
- он определяется содержимым `Machines` resource tree в момент запуска;
- названия preset в UI происходят из имен файлов и каталогов.

### What a preset definition looks like

Preset definition — это не только “device transport config”. На примерах видно, что `.aset` preset может включать:

- `[General]`
- `[Device]`
- `[Modbus]` / `[S7]` / `[WebSocket]` / другие transport-specific sections
- `[DefaultButtons]`
- `[ExtraDev]`
- `[ExtraEventButtons]`
- `[Sliders]`
- `[Quantifiers]`
- `[EnergyDefaults]`
- `[MachineSetup]`

Прямые примеры:

- `src/includes/Machines/Coffed/SR5_automatic.aset:1-115`
- `src/includes/Machines/iRm Series/Mitsubishi_PLC.aset:1-220`
- `src/includes/Machines/Probat/G_UG_WebSockets.aset:1-120`

Это означает, что preset definitions представлены как смесь:

- resource files `.aset`
- значения QSettings groups inside those files
- в некоторых полях serialized Python/Qt variants, например `EnergyDefaults.ratings`

Отдельного Python-класса вроде `MachinePreset` в исходниках не обнаружено.

### Table 1 - Preset definition map

| Компонент | Где найден | Что хранит | Насколько это hardcoded | Комментарий |
|---|---|---|---|---|
| Built-in machine library | `src/includes/Machines/**.aset` | machine presets по брендам и моделям | Низко: файловая библиотека | Основной источник supported machines |
| Dynamic menu discovery | `src/artisanlib/main.py:5782-5854` | обход папки `Machines`, grouping, menu actions | Средне: код hardcoded, список файлов нет | Меню строится из содержимого каталога |
| `machineMenu` UI entry point | `src/artisanlib/main.py:2478-2481`, `4399` | menu entry в Config/главном UI | Hardcoded UI entry | Только точка входа, не источник preset data |
| Packaging rules | `src/artisan-mac.spec:106`, `src/artisan-win.spec:298-299`, `src/build-linux-buster.sh:126-128` | включение `Machines` в дистрибутив | Hardcoded build-time | Подтверждает, что library shipped as files |
| Generic `.aset` settings format | `src/artisanlib/main.py:18011-19095`, `20171+` | общий import/export settings schema | Hardcoded code + file format | Machine presets используют тот же механизм |
| Energy defaults blob | `EnergyDefaults.ratings` inside `.aset` examples | per-machine energy defaults keyed by heating/capacity | Mixed | Хранится как serialized Qt/Python object, не как чистый INI schema |

## Preset selection flow

### Real call chain

Реальная цепочка применения built-in preset:

1. Пользователь открывает меню `Machine`.
   - `src/artisanlib/main.py:2478`, `4399`
2. Меню уже заполнено `populateMachineMenu()`.
   - `src/artisanlib/main.py:5853-5854`
3. Пользователь выбирает конкретный `QAction`.
4. `openMachineSettings()` получает `action.data()` с абсолютным путем к `.aset`.
   - `src/artisanlib/main.py:5857-5867`
5. После подтверждения диалога вызывает:
   - `self.loadSettings(fn=action.data()[0], remember=False, machine=True, reload=False)`
   - `src/artisanlib/main.py:5895`
6. `loadSettings()` вызывает:
   - `self.settingsLoad(filename, machine=machine, theme=theme, redraw=not reset)`
   - `src/artisanlib/main.py:24981-24989`
7. `settingsLoad()` читает `.aset` через `QSettings(filename, IniFormat)`.
   - `src/artisanlib/main.py:18022`
8. Далее preset-группы маппятся в runtime fields.
   - device/transport/UI/etc в `settingsLoad()`
9. После загрузки `openMachineSettings()` может дополнительно спросить host/comport/capacity/heating и донастроить runtime.
   - `src/artisanlib/main.py:5919-6081`
10. Если пользователь отменяет этот flow, часть полей откатывается к сохраненным значениям.
    - `src/artisanlib/main.py:6082-6100`

### What `openMachineSettings()` adds on top of file loading

`openMachineSettings()` не просто грузит `.aset`, а оборачивает его дополнительной логикой:

- перед загрузкой сохраняет исходные значения:
  - `org_device`, `org_machinesetup`, `org_modbus_host`, `org_s7_host`, `org_ws_host`, `org_comport`, `org_modbus_comport`, `org_roastersize_setup`, и др.
  - `src/artisanlib/main.py:5878-5887`
- сбрасывает machine-setup defaults:
  - `roastersize_setup_default = 0`
  - `roasterheating_setup_default = 0`
  - `roastersize_setup = 0`
  - `roasterheating_setup = 0`
  - `src/artisanlib/main.py:5888-5893`
- после загрузки preset в зависимости от выбранного device family может попросить:
  - Modbus host (`5920-5929`)
  - S7 host (`5931-5940`)
  - WebSocket host (`5942-5951`)
  - Kaleido host (`5953-5962`)
  - Mugma host (`5964-5973`)
  - serial/modbus COM port (`5974-6000`)
  - capacity (`6002-6017`)
  - heating type (`6025-6034`)
- затем применяет energy defaults, если они есть для выбранной heating/capacity combination (`6036-6081`)

Следовательно, preset selection flow — это не просто “load file”; это “load partial settings snapshot + interactive runtime specialization”.

## Mapping from preset to runtime/config

### Generic mechanism

Preset-файл применяет настройки через общий `settingsLoad()` path. Machine preset не получает отдельный parser layer. Это значит:

- все группы `.aset`, которые `settingsLoad()` умеет читать, потенциально могут мутировать runtime;
- preset может затрагивать намного больше, чем только device layer.

Это видно на примерах:

- `Coffed/SR5_automatic.aset` задает `[Device]`, `[Modbus]`, `[Sliders]`, `[EnergyDefaults]`, `[MachineSetup]`
- `Probat/G_UG_WebSockets.aset` задает `[Device]`, `[DefaultButtons]`, `[ExtraDev]`, `[ExtraEventButtons]`, `[Sliders]`, `[WebSocket]`, `[EnergyDefaults]`
- `iRm Series/Mitsubishi_PLC.aset` задает `[ArduinoPID]`, `[DefaultButtons]`, `[ExtraDev]`, `[ExtraEventButtons]`, `[Modbus]`, `[Quantifiers]`, `[Sliders]`, `[EnergyDefaults]`

### Concrete preset-driven runtime mutations

#### Device family / transport choice

- `Coffed/SR5_automatic.aset`
  - `[Device] id=29` => main device is Modbus
  - `[Modbus] type=3 host=10.0.0.100 port=502 ...`
  - `src/includes/Machines/Coffed/SR5_automatic.aset:6-92`
- `Probat/G_UG_WebSockets.aset`
  - `[Device] id=111` => main device is WebSocket
  - `[WebSocket] host, port, path, node names, channel mappings, request_data_command`
  - `src/includes/Machines/Probat/G_UG_WebSockets.aset:17-118`

В runtime эти значения попадают через `settingsLoad()`:

- `[Device]` -> `self.qmc.device` в `src/artisanlib/main.py:18166-18212`
- `[Modbus]` -> `self.modbus.*` в `src/artisanlib/main.py:18570-18621`
- `[WebSocket]` -> `self.ws.*` в более поздней части `settingsLoad()`; этот path уже подтверждался в предыдущем исследовании websocket layer

#### Channel mappings / scaling / conversions

- `Coffed/SR5_automatic.aset`
  - `input1deviceId=1`, `input1register=0`, `input1code=3`, `input1div=2`, `input1mode=C`
  - `input2deviceId=1`, `input2register=10`, ...
  - `src/includes/Machines/Coffed/SR5_automatic.aset:20-38`
- `Probat/G_UG_WebSockets.aset`
  - `channel_modes=1,1,0,...`
  - `channel_nodes=beanTemp, ambientTemp, burner, ...`
  - `src/includes/Machines/Probat/G_UG_WebSockets.aset:98-100`

В runtime это потом читает соответствующий backend/sampling bridge:

- Modbus mapping -> `self.modbus.input*` через `settingsLoad()` and then `comm.MODBUSread()`
- WebSocket mapping -> `self.ws.channel_*` через `settingsLoad()` and then `comm.WSread()`

#### Event / command mappings

- `Probat/G_UG_WebSockets.aset`
  - `charge_message`, `drop_message`, `addEvent_message`, `request_data_command`
  - `DRY_node`, `FCs_node`, `FCe_node`, `SCs_node`, `SCe_node`
  - `buttonactionstrings`, `slidercommands`, `extraeventsactionstrings`
  - `src/includes/Machines/Probat/G_UG_WebSockets.aset:8-16`, `45-79`, `88-118`
- `iRm Series/Mitsubishi_PLC.aset`
  - Modbus write commands in buttons/sliders:
  - `writeSingle(1,11,1)`, `writeSingle(1,514,1);writeSingle(1,514,0)`, `writeSingle(1,300,{})`
  - `src/includes/Machines/iRm Series/Mitsubishi_PLC.aset:33-41`, `71-78`, `188-198`

Это попадает не в отдельный machine action layer, а в общие button/slider/event settings, которые позже использует `eventaction()`.

#### Machine metadata and energy defaults

Machine setup groups читаются в `settingsLoad()` специально:

- если `filename and machine`:
  - `[MachineSetup] capacity` -> `self.qmc.roastersize_setup`
  - `[MachineSetup] heating_type` -> `self.qmc.roasterheating_setup`
  - `src/artisanlib/main.py:18964-18971`
- общие setup fields:
  - `organization_setup`, `operator_setup`, `roastertype_setup`, `roastersize_setup_default`, `roasterheating_setup_default`
  - `src/artisanlib/main.py:18973-18980`
- `[EnergyUse]` and `[EnergyDefaults]`
  - setup arrays + `ratings`
  - `src/artisanlib/main.py:18982-19015`
- потом значения копируются в active roast properties:
  - `self.qmc.roastertype = self.qmc.roastertype_setup`
  - `self.qmc.roastersize = self.qmc.roastersize_setup`
  - `self.qmc.roasterheating = self.qmc.roasterheating_setup`
  - `src/artisanlib/main.py:19031-19036`

### Table 2 - Preset to runtime/config mapping

| Элемент preset | Где применяется | На что влияет | Можно ли override вручную |
|---|---|---|---|
| `.aset` file path from menu | `main.py:5857-5895` | запускает `loadSettings(machine=True)` | Нет, это сам entry point |
| `[Device].id` | `main.py:18166-18212` | выбирает main device family/runtime dispatch | Да, через Device/Ports settings |
| `[Modbus]`, `[S7]`, `[WebSocket]` transport fields | `settingsLoad()` соответствующих групп | backend transport/protocol runtime state | Да, через Ports dialog и subsequent save |
| Channel mappings (`input*`, `channel_*`, `area/db/start/type`) | `settingsLoad()` -> backend state -> `comm.*read()` | какие machine values попадают в runtime channels | Да, в device/ports setup |
| `buttonactionstrings`, `slidercommands`, `extraeventsactionstrings` | общие settings groups + `eventaction()` runtime use | operator controls and command routing | Да, через Events/Buttons/Sliders UI, если пользователь редактирует |
| `roastertype_setup`, `roastersize_setup_default`, `capacity`, `heating_type` | `main.py:18964-19036`, `6002-6034` | machine metadata, default batch size, heating choice | Да, часть — через prompt при выборе machine, часть — через Roast Properties |
| `EnergyDefaults.ratings` | `main.py:19012-19015`, `6036-6081` | default energy loads/protocol per capacity+heating | Частично: runtime can later edit energy settings |
| `ExtraDev`, `ExtraEventButtons`, `Sliders`, `Quantifiers` | общий `settingsLoad()` path | extra channels, controls, UI behavior | Да, через соответствующие dialogs |
| `machinesetup` / machine labels | `main.py:19038+` and `openMachineSettings()` | current machine label shown in runtime/profile metadata | Да |

## Editable vs fixed preset parts

### What preset sets automatically

На основании реальных `.aset` examples и `settingsLoad()` preset автоматически может задать:

- device backend family (`[Device].id`)
- transport settings for backend
- channel/address mapping
- scaling / mode conversion flags
- button/slider/extra-event command bindings
- extra devices and channel names
- machine metadata (`roastertype_setup`, size defaults, heating defaults)
- energy defaults

Это не inference “в общем случае”, а прямое следствие того, что `.aset` sections читаются общим settings loader’ом и в примерах эти поля реально присутствуют.

### What user can still change after applying preset

По коду после применения preset пользователь может:

- подтвердить или переопределить network host / serial port / capacity / heating прямо в `openMachineSettings()`
  - `src/artisanlib/main.py:5919-6034`
- дальше открыть обычные dialogs и менять те же runtime fields
  - device/ports, roast properties, events/sliders, energy settings
- сохранить результат как пользовательский `.aset`
  - `saveSettings()` в `src/artisanlib/main.py:25087-25109`

### Where preset/user override boundary actually sits

Граница устроена так:

1. built-in preset mutates runtime via `settingsLoad(machine=True)`
2. machine-selection flow adds immediate interactive overrides
3. later UI changes mutate same runtime state
4. `saveSettings()` serializes current state to a user `.aset`

Это важно: в Artisan built-in preset и user-defined settings используют один и тот же underlying format. Отдельного immutable preset layer поверх mutable overrides нет.

## What to carry into the new product

### Useful product ideas

1. Оставить как идею: файловую библиотеку built-in presets, grouped by brand/model.
   - Основание: `includes/Machines` + dynamic discovery in `populateListMenu()`.
   - Пользовательская ценность: библиотеку можно расширять без переписывания UI registry.
2. Оставить как идею: machine preset как partial config snapshot, а не код.
   - Основание: `.aset` presets реально задают transport + mapping + controls + machine metadata.
   - Это хорошо переносится в новый продукт как declarative compatibility layer.
3. Оставить как идею: post-load specialization prompts.
   - Основание: host/comport/capacity/heating prompts in `openMachineSettings()`.
   - Хорошо подходит, если один preset должен быстро адаптироваться под конкретную установку.
4. Оставить как идею: brand/model hierarchy in preset picker.
   - Основание: directories become submenus automatically.

### Weak / legacy parts

1. Переосмыслить: machine preset как общий settings dump.
   - Почему: preset может мутировать слишком много несвязанных слоев UI/runtime.
2. Переписать: отсутствие отдельной typed preset schema.
   - Почему: сейчас смысл полей определяется тем, что именно умеет читать `settingsLoad()`.
3. Переписать: смешение built-in preset, mutable runtime state и user-saved settings в одном формате.
   - Почему: тяжело отделить vendor baseline от user override delta.
4. Переосмыслить: serialized blobs вроде `EnergyDefaults.ratings` в Qt variant form.
   - Почему: плохо переносимо, слабо читаемо, неудобно для внешних tooling and tests.
5. Переосмыслить: отсутствие отдельной user preset library рядом с built-ins.
   - Почему: пользователь может сохранять `.aset` куда угодно, но нет чистой модели “vendor preset -> clone -> customized preset”.

### Table 3 - Recommendation for new architecture

| Элемент Artisan | Оставить как идею / переосмыслить / переписать | Почему |
|---|---|---|
| `includes/Machines/<Brand>/<Preset>.aset` library | Оставить как идею | Хорошая product-level модель built-in preset catalog |
| Dynamic discovery through filesystem scan | Оставить как идею | Упрощает расширение preset library без кодовых registries |
| Menu grouping by directory/brand | Оставить как идею | Понятная UX-структура для большого каталога |
| Machine preset as generic settings file | Переосмыслить | Слишком широкий blast radius, preset смешан с UI/app state |
| Single `settingsLoad()` path for presets and user settings | Переосмыслить | Удобно, но размывает границу baseline vs override |
| Interactive specialization after preset load | Оставить как идею | Практичный компромисс для host/comport/capacity |
| Energy defaults stored as Qt serialized variant blobs | Переписать | Плохо тестируется и нечитабельно вне Qt |
| No separate user machine preset namespace | Переписать | Для нового продукта лучше явный vendor/user/custom compatibility layer |
| Saving current state to `.aset` | Оставить как compatibility idea | Полезно для migration/import-export story, но не как canonical internal model |

## Open questions

1. В этом разборе не строился полный coverage map по всем 252 `.aset`, поэтому нельзя строго утверждать, какие секции являются де-факто стандартными для большинства presets, а какие встречаются только у отдельных машин.
   - Что проверить дополнительно: массовый анализ section frequency across all preset files.
   - Уровень уверенности: средний.
2. Не найден отдельный `Machines/User` flow, но пользовательские `.aset` можно сохранять и загружать вручную через `Save Settings...` / `Load Settings...`.
   - Что проверить дополнительно: не создается ли user machine library в runtime data dir outside repo tree.
   - Уровень уверенности: средний.
3. По коду видно, что machine preset может менять почти весь settings state, но точный “safe subset” для нового продукта как compatibility import layer нужно определять отдельным schema audit’ом по `settingsLoad()`.
   - Уровень уверенности: высокий.
