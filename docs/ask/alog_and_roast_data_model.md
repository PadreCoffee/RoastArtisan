# `.alog` and Roast Data Model in Artisan

## Executive summary

`*.alog` в Artisan не выглядит как внутренний canonical runtime format. По цепочке `fileLoad()` -> `deserialize()` -> `setProfile()` и `fileSave()` -> `getProfile()` -> `serialize()` видно, что runtime состояние живет прежде всего в `self.qmc` (`tgraphcanvas`), а `.alog` является сохраненным представлением этого состояния, дополненным метаданными, UI-настройками и частью precomputed summary. Основание: `src/artisanlib/main.py:13631-13658`, `src/artisanlib/main.py:17013-17231`, `src/artisanlib/main.py:17313-17348`, `src/artisanlib/util.py:973-986`.

Отдельного богатого parser/serializer layer для `.alog` нет. Чтение и запись сводятся к `ast.literal_eval()` и `repr(obj)`, то есть формат является Python-literal serialization словаря. Основание: `src/artisanlib/util.py:973-986`. Уверенность высокая.

Внутренняя модель roast/session/profile не отделена от UI-layer. Главный контейнер состояния фактически `tgraphcanvas`, который держит одновременно live curves, events, smoothed/derived arrays, background profile, annotation positions и множество display/config state. Основание: `src/artisanlib/canvas.py:203`, `src/artisanlib/canvas.py:252`, `src/artisanlib/canvas.py:7812`, `src/artisanlib/canvas.py:8035-8038`, `src/artisanlib/canvas.py:17956`, `src/artisanlib/main.py:15721-16434`. Уверенность высокая.

Для нового продукта `.alog` разумнее поддерживать как compatibility layer, а не как внутреннюю модель. Код Artisan показывает, что формат смешивает roast core data, UI preferences, style metadata, alarms, PID/ramp-soak, energy и annotations в одном persisted object (`ProfileData`). Основание: `src/artisanlib/atypes.py:128-240`, `src/artisanlib/main.py:17013-17231`. Рекомендация import+export через адаптер имеет высокую уверенность; рекомендация делать внутреннюю модель близкой к `.alog` имеет низкую привлекательность по коду.

## Where `.alog` is implemented

### Основные файлы и роли

1. `src/artisanlib/util.py`
   Чтение и запись `.alog` делаются через `deserialize()` и `serialize()`.
   `serialize()` пишет `repr(obj)` в файл, `deserialize()` читает файл и вызывает `ast.literal_eval()`: `src/artisanlib/util.py:973-986`.

2. `src/artisanlib/atypes.py`
   `ProfileData` задает явную типизированную схему persisted profile object, который и сериализуется в `.alog`: `src/artisanlib/atypes.py:128-240`.

3. `src/artisanlib/main.py`
   UI entry points и orchestration:
   `fileLoad()` -> `loadFile()` для загрузки: `src/artisanlib/main.py:13614`, `src/artisanlib/main.py:13631`.
   `fileSave()` для сохранения: `src/artisanlib/main.py:17313`.
   `fileConvertFrom()` и `fileConvert()` для import/export pipelines: `src/artisanlib/main.py:17503`, `src/artisanlib/main.py:17552`.
   `loadbackground()` для загрузки `.alog` как background profile: `src/artisanlib/main.py:14182`.
   `setProfile()` hydrates persisted object into runtime: `src/artisanlib/main.py:15721`.
   `getProfile()` materializes persisted object from runtime: `src/artisanlib/main.py:17013`.

4. `src/artisanlib/canvas.py`
   `tgraphcanvas` хранит live/session/profile state, которое затем читается `getProfile()` и заполняется `setProfile()`: `src/artisanlib/canvas.py:203`, `src/artisanlib/canvas.py:252`.

### Чтение `.alog`

Основная цепочка:

1. UI вызывает `fileLoad()` из menu action: `src/artisanlib/main.py:13614-13621`.
2. `loadFile(filename)` открывает файл, проверяет первый символ `{`, затем вызывает `deserialize(filename)`: `src/artisanlib/main.py:13631-13649`.
3. Результат приводится к `ProfileData`, затем передается в `setProfile(filename, obj, quiet=quiet, reset=False)`: `src/artisanlib/main.py:13649-13658`.
4. `setProfile()` раскладывает persisted data обратно в `self.qmc.*`, UI labels, alarms, extra devices, axis state и annotations: `src/artisanlib/main.py:15721-16434`.

Это не parser в смысле отдельного domain layer; это UI-driven hydration persisted dict в большой runtime object.

### Запись `.alog`

Основная цепочка:

1. UI вызывает `fileSave()`: `src/artisanlib/main.py:17313`.
2. `fileSave()` вызывает `pf = self.getProfile()`: `src/artisanlib/main.py:17330`.
3. `getProfile()` собирает `ProfileData` из `self.qmc` и связанных UI/settings state: `src/artisanlib/main.py:17013-17231`.
4. `fileSave()` вызывает `serialize(filename, pf)`: `src/artisanlib/main.py:17344-17348`.

### Есть ли отдельный parser/serializer layer

Нет, если судить строго по коду. Есть только thin utility layer:

- `serialize()` / `deserialize()` в `src/artisanlib/util.py:973-986`
- schema в `src/artisanlib/atypes.py:128-240`
- вся содержательная логика shape conversion/hydration находится в `getProfile()` / `setProfile()` в `src/artisanlib/main.py`.

Уверенность высокая.

### `.alog` — основной внутренний формат или экспортное представление runtime state

По коду `.alog` ближе к native persisted profile format, но не к runtime canonical state.

Основания:

- runtime sample arrays живут в `self.qmc.timex/temp1/temp2/...`: `src/artisanlib/canvas.py:17956`, `src/artisanlib/canvas.py:7812`, `src/artisanlib/canvas.py:8035-8038`;
- persisted object строится отдельно в `getProfile()`: `src/artisanlib/main.py:17013-17231`;
- при загрузке этот object потом гидратируется обратно через `setProfile()`: `src/artisanlib/main.py:15721-16434`;
- import других форматов сначала превращается в `ProfileData`, затем сохраняется как `.alog`: `src/artisanlib/main.py:17503-17538`;
- export в другие форматы сначала читает `.alog`, потом делает `setProfile()`, затем redraw/format-specific dumper: `src/artisanlib/main.py:17552-17584`.

Формулировка с максимальной точностью: `.alog` в Artisan является native persisted interchange/save format для roast profile, а не runtime in-memory model. Уверенность высокая.

## Runtime roast/session model

### Где живет текущая roast session

Главный runtime owner: `tgraphcanvas` (`self.qmc`) в `src/artisanlib/canvas.py:203`.

Прямые признаки god-object:

- огромный `__slots__`: `src/artisanlib/canvas.py:252`;
- main arrays и event state инициализируются и сбрасываются прямо внутри `canvas.py`:
  - `self.unfiltereddelta1,self.unfiltereddelta2 = [],[]`: `src/artisanlib/canvas.py:7806`
  - `self.timeindex = [-1,0,0,0,0,0,0,0]`: `src/artisanlib/canvas.py:7812`
  - `self.specialevents = []`, `self.specialeventstype = []`, `self.specialeventsStrings = []`, `self.specialeventsvalue = []`: `src/artisanlib/canvas.py:8035-8038`
  - `self.timex,self.temp1,self.temp2 = [],[],[]`: `src/artisanlib/canvas.py:17956`

### Где живут samples/channels

Live sampling pipeline:

1. `SampleThread.run()` циклически вызывает `sample()`: `src/artisanlib/canvas.py:19686-19737`.
2. `sample()` берет readings с main и extra devices: `src/artisanlib/canvas.py:19623-19660`.
3. Main device sampling идет через `sample_main_device()` -> `self.aw.ser.devicefunctionlist[self.aw.qmc.device]()`; это дает `(tx, t1, t2)` и при `swapETBT` меняет местами ET/BT: `src/artisanlib/canvas.py:19593-19606`.
4. Extra devices идут через `sample_extra_device(i)` -> `self.aw.extraser[i].devicefunctionlist[self.aw.qmc.extradevices[i]]()`: `src/artisanlib/canvas.py:19609-19619`.
5. Затем `sample_processingSignal` передает readings в GUI thread и `sample_processing()` уже пишет их в runtime arrays: `src/artisanlib/canvas.py:19661-19664`, `src/artisanlib/canvas.py:4658-4719`.

Отсюда граница ясная:

- raw machine values приходят из `devicefunctionlist[...]()` в sampling layer;
- operator-visible roast curves живут в `self.qmc.timex/temp1/temp2` и extra arrays после `sample_processing()`.

### Где хранятся events/annotations

Roast events хранятся не как объектный список, а как четыре параллельных массива:

- `specialevents`
- `specialeventstype`
- `specialeventsStrings`
- `specialeventsvalue`

Их initialization/reset видны в `src/artisanlib/canvas.py:8035-8038` и `src/artisanlib/canvas.py:19041-19070`.

`main.py` отдельно следит за консистентной длиной этих массивов через `consolidateSpecialEvents()`: `src/artisanlib/main.py:15713-15716`, а потом сохраняет/загружает их через `getProfile()` / `setProfile()`: `src/artisanlib/main.py:16202-16208`, `src/artisanlib/main.py:17115-17118`.

Annotations и flag positions сохраняются отдельно:

- save: `profile['anno_positions'] = self.qmc.getAnnoPositions()`, `profile['flag_positions'] = self.qmc.getFlagPositions()`: `src/artisanlib/main.py:17230-17231`
- load: `self.qmc.setAnnoPositions(profile['anno_positions'])`, `self.qmc.setFlagPositions(profile['flag_positions'])`: `src/artisanlib/main.py:16344-16348`

### Где хранятся device/control values

В persisted profile есть большой блок machine/operator metadata и control-related state:

- `roastertype`, `roastersize`, `roasterheating`, `machinesetup`, `drumspeed`: `src/artisanlib/atypes.py:161-167`
- alarm fields: `alarmflag`, `alarmguard`, `alarmtime`, `alarmtemperature` и др.: `src/artisanlib/atypes.py:254-265` и загрузка/сохранение в `main.py`
- extra devices metadata and styles: `extradevices`, `extraname*`, `extraDelta*`, `extramathexpression*`, etc.: `src/artisanlib/atypes.py:222-240`

В runtime они также живут на `self.qmc` и в родительском `ApplicationWindow`; `setProfile()` и `getProfile()` постоянно переходят между `self.qmc.*`, `self.*` и UI flags. Основание: `src/artisanlib/main.py:15721-16434`, `src/artisanlib/main.py:17013-17231`.

### Где формируется “profile” как сохраненный объект

В `getProfile()`: `src/artisanlib/main.py:17013-17231`.

Это не просто curves dump. В profile включаются:

- raw roast arrays `timex/temp1/temp2`;
- events;
- extra channels;
- metadata roast/session;
- axis/style/UI-related fields;
- alarms;
- computed summary block: `profile['computed'] = self.computedProfileInformation()`: `src/artisanlib/main.py:17228`.

### Граница между live session data и saved profile

По коду граница функционально есть, но архитектурно слабая:

- live runtime: `self.qmc.*` arrays и flags в `canvas.py`;
- saved profile: `ProfileData` dict в `atypes.py`;
- bridge: `getProfile()` и `setProfile()` в `main.py`.

Проблема в том, что `saved profile` включает много UI/config state, поэтому это не чистый domain snapshot roast session. Основание: множество display/style/alarm fields в `ProfileData`, `src/artisanlib/atypes.py:128-280`.

## Saved profile model

`ProfileData` в `src/artisanlib/atypes.py:128-240` является самой явной формализацией persisted model.

### Что явно есть как сущности

Явные сущности, которые действительно можно выделить по коду:

1. `ProfileData`
   Persisted dict schema.

2. `ComputedProfileInformation`
   Derived summary block, который сохраняется внутрь profile как `computed`: `src/artisanlib/main.py:16704-17011`, `src/artisanlib/main.py:17228`.

3. `tgraphcanvas`
   Runtime/session state holder, хотя это не чистая domain entity: `src/artisanlib/canvas.py:203`.

### Что существует неявно, размазано по state/UI

1. Roast session
   Не отдельный класс, а набор полей `self.qmc.timex/temp1/temp2/extratemp*/timeindex/specialevents/...`.

2. Roast profile
   Не отдельный объект с поведением, а dict, который собирается/разбирается через `getProfile()` / `setProfile()`.

3. Event/annotation model
   Реализована параллельными массивами и UI helper methods, а не структурированными record objects.

4. Device snapshot/control snapshot
   Частично живут как сериализуемые поля, частично как runtime `self.qmc`/`self.*` state, без четкого boundary object.

### Background profile как отдельный слой

Есть важное разделение foreground vs background:

- foreground session/profile загружается через `setProfile()` в `self.qmc.timex/temp1/temp2/...`;
- background profile загружается через `loadbackground()` в `self.qmc.temp1B/temp2B/timeB/...`: `src/artisanlib/main.py:14182-14316`.

Это полезная концепция: comparison/reference profile отделен от live foreground отдельным storage, хотя все еще внутри того же god-object.

## Channels, events, metrics

### Где определяются каналы BT/ET/extra channels

Основные каналы:

- `temp1` и `temp2` приходят из `sample_main_device()`, где комментарий явно говорит `ET (t1) and BT (t2)`: `src/artisanlib/canvas.py:19593-19601`.
- Если включен `swapETBT`, они меняются местами до записи в runtime: `src/artisanlib/canvas.py:19597-19601`.

Extra channels:

- для каждого extra device `sample_extra_device(i)` возвращает `(tx, t1, t2)`: `src/artisanlib/canvas.py:19609-19619`;
- `sample()` добавляет их в `temp1_readings/temp2_readings/timex_readings`: `src/artisanlib/canvas.py:19654-19658`;
- `setProfile()`/`getProfile()` сохраняют и загружают их как `extratimex`, `extratemp1`, `extratemp2`: `src/artisanlib/main.py:15753-15858`, `src/artisanlib/main.py:17136-17158`.

### Как хранятся arrays / samples / timestamps

Основные persisted arrays:

- `timex`, `temp1`, `temp2`: `src/artisanlib/atypes.py:206-208`
- extra arrays: `extratimex`, `extratemp1`, `extratemp2`: `src/artisanlib/atypes.py:225-227`

Runtime arrays:

- foreground `self.qmc.timex/temp1/temp2`
- smoothed/filtered/delta arrays in `sample_processing()` such as `sample_ctemp1`, `sample_tstemp1`, `sample_unfiltereddelta1`, `sample_delta1`: `src/artisanlib/canvas.py:4680-4719`
- background arrays `temp1B/temp2B/timeB/...` in `loadbackground()`: `src/artisanlib/main.py:14253-14312`

### Где считаются derived metrics

1. Online RoR estimate:
   `compute_ror()` и `compute_ror_simple()` в `src/artisanlib/canvas.py:4614-4654`.
   Здесь RoR считается либо через linear fit (`polyfitRoRcalc`), либо через simpler delta window.

2. Derived sample arrays online:
   `sample_processing()` обновляет `unfiltereddelta*`, `delta*`, filtered/smoothed arrays: `src/artisanlib/canvas.py:4658-4719`.

3. Saved summary metrics:
   `computedProfileInformation()` вычисляет TP/DRY/FC/SC/DROP metrics, phase times, phase RoR, AUC, weight/volume losses, humidity, similarity, energy, BBP: `src/artisanlib/main.py:16704-17011`.
   Этот блок потом сохраняется как `profile['computed']`: `src/artisanlib/main.py:17228`.

4. Redraw-triggered recomputation:
   UI changes к smoothing/curve settings вызывают `qmc.redraw(recomputeAllDeltas=True, ...)` из `curves.py`: `src/artisanlib/curves.py:1493`, `src/artisanlib/curves.py:2407`, `src/artisanlib/curves.py:2608`, `src/artisanlib/curves.py:2674`.
   Это признак, что часть derived state зависит от current render/config cycle, а не только от raw saved data.

### Что считается online, а что при сохранении / post-process

Online / runtime:

- sampling from devices;
- filtered and smoothed arrays;
- RoR arrays (`delta*`);
- часть redraw-driven recomputation.

Основание: `src/artisanlib/canvas.py:4614-4719`, `src/artisanlib/canvas.py:19623-19664`.

On save / persisted summary:

- `computedProfileInformation()` -> `profile['computed']`: `src/artisanlib/main.py:16704-17011`, `src/artisanlib/main.py:17228`.

Background-load post-process:

- smoothing and fill-gaps for background curves during `loadbackground()`: `src/artisanlib/main.py:14274-14312`.

### Как в `.alog` представлены channels/events/derived values

Channels:

- main arrays: `timex`, `temp1`, `temp2`
- extra arrays: `extratimex`, `extratemp1`, `extratemp2`

Events:

- `timeindex` для landmark events CHARGE/DRY/FCs/FCe/SCs/SCe/DROP/COOL: initialization comment/value pattern visible via `src/artisanlib/canvas.py:7812`; usage in `computedProfileInformation()` directly maps those indices to named roast milestones: `src/artisanlib/main.py:16710-16766`.
- custom/operator events: `specialevents`, `specialeventstype`, `specialeventsvalue`, `specialeventsStrings`: `src/artisanlib/atypes.py:197-200`

Derived:

- не весь derived runtime сохраняется как full arrays;
- summary сохраняется в `computed`;
- отдельные flags about extra delta curves (`extraDelta1/2`) сохраняются как display/interpretation metadata.

### Что выглядит удачной концепцией, а что смешением слоев

Удачные концепции:

- raw sample streams отдельно от summary metrics;
- explicit `timeindex` landmarks для ключевых фаз;
- foreground/background profile separation;
- derived summary block `computed`, отделенный от raw arrays.

Смешение слоев:

- events как параллельные массивы;
- `.alog` содержит и roast data, и UI/style/alarm state;
- recomputation derived values зависит от redraw/render pipeline;
- runtime and saved profile tightly coupled через `self.qmc`.

## Import/export pipeline

### Load existing profile

`fileLoad()` -> `loadFile()` -> `deserialize()` -> `setProfile()`: `src/artisanlib/main.py:13614-13658`.

### Save current roast

`fileSave()` -> `getProfile()` -> `serialize()`: `src/artisanlib/main.py:17313-17348`.

### Import external formats

`fileConvertFrom()` берет extractor specific to foreign format, получает `ProfileData`, затем сразу пишет его как `.alog`: `src/artisanlib/main.py:17503-17538`.

Это очень важное инженерное наблюдение: совместимость с внешними форматами в Artisan уже строится через intermediate native profile dict, а не через shared abstract serialization framework.

### Export to other formats

`fileConvert()` открывает `.alog`, делает `deserialize()`, затем `setProfile()`, затем `self.qmc.redraw()` и только потом вызывает format-specific `dumper`: `src/artisanlib/main.py:17552-17584`.

Это означает:

- export depends on hydrated UI/runtime state;
- часть derived/exported значений зависит от того, что `redraw()` заполнит delta lines;
- parser/serializer не полностью отделим от UI without refactoring.

### Есть ли общая serialization layer

Строго по коду нет.

Есть:

- общий low-level read/write helper (`serialize` / `deserialize`);
- много special-case load/save logic в `getProfile()`, `setProfile()`, `loadbackground()`, format-specific extractors/dumpers.

### Можно ли отделить parser/serializer от UI

Частично да, но не напрямую.

Что отделяется сравнительно чисто:

- `.alog` file I/O (`repr`/`literal_eval`);
- `ProfileData` schema;
- mapping between `.alog` dict and a new canonical domain model.

Что сейчас завязано на UI/state:

- `setProfile()` и `getProfile()` трогают `self.qmc`, dialogs, axis settings, LCD visibility, slider labels, alarms, background handling;
- `fileConvert()` требует `setProfile()` + `redraw()`.

Поэтому для нового проекта поддержка `.alog` как отдельного compatibility layer выглядит реалистичной, но не через прямой reuse функции `setProfile()`/`getProfile()`. Уверенность высокая.

### Основные риски по совместимости

1. Формат основан на Python literal serialization, а не на строгой спецификации.
   Основание: `src/artisanlib/util.py:973-986`.

2. Поля `.alog` смешивают core roast data и UI/settings.
   Основание: `src/artisanlib/atypes.py:128-240`.

3. Некоторые экспортируемые/derived значения зависят от redraw/recompute cycle.
   Основание: `src/artisanlib/main.py:17569-17574`, `src/artisanlib/curves.py:1493`.

4. Legacy/compat branches влияют на interpretation:
   date formats, `beansize` legacy mapping, unit conversions, profile mode conversion.
   Основание: `src/artisanlib/main.py:16063-16152`, `src/artisanlib/main.py:16232-16341`.

## Coupling with UI/state

### Насколько roast/profile model живет в UI-layer

Сильно.

Примеры:

- `loadFile()` после `setProfile()` сразу обновляет `etypeComboBox`, current file, LCDs, background visibility и axis: `src/artisanlib/main.py:13658-13737`.
- `setProfile()` меняет slider labels, extra LCD layout, button alignment, axis limits, legend placement, alarms, background, redraw-relevant settings: `src/artisanlib/main.py:15721-16434`.
- `fileConvert()` для export зависит от `self.qmc.redraw()`: `src/artisanlib/main.py:17569-17574`.

### Есть ли global/shared state

Да, фактически `self.qmc` выступает shared mutable state для roast data, UI-related configuration и derived caches. Основание: `src/artisanlib/canvas.py:203`, `src/artisanlib/canvas.py:252`, `src/artisanlib/main.py:15721-16434`, `src/artisanlib/main.py:17013-17231`.

### Есть ли god-object

Да: `tgraphcanvas`.

Это наиболее уверенный архитектурный вывод по коду.

### Что слишком срослось с UI

1. Profile hydration/saving.
2. Axis/display/style metadata.
3. Event rendering assumptions.
4. Recompute of derived arrays through redraw pipeline.

## What to carry into the new product

### Рекомендация по canonical format

На основе кода Artisan внутренний canonical format нового продукта лучше делать своим, а не близким к `.alog`.

Причина:

- `.alog` содержит слишком много UI-specific и legacy state;
- runtime в Artisan все равно не опирается на `.alog` как на canonical in-memory object;
- compatibility already works through translation layer (`extractor -> ProfileData -> .alog`).

### Разумная стратегия поддержки `.alog`

Наиболее обоснованный вариант по исходникам:

1. `import only` как минимум обязателен, если нужна совместимость.
2. `import + export via compatibility layer` выглядит реалистично и инженерно разумно.
3. `internal model close to .alog` выглядит слабее, потому что унаследует смешение слоев.

Уверенность:

- import via adapter: высокая;
- export via adapter: средне-высокая;
- canonical model close to `.alog`: низкая рекомендация.

### Какие сущности напрашиваются для нового приложения

На основе того, что реально есть в Artisan, а не “с нуля”:

1. `RoastSession`
   Live run with sample streams, machine snapshots, operator actions.

2. `RoastProfile`
   Persisted roast record for storage/import/export.

3. `Channel`
   BT/ET/extra logical channels with metadata.

4. `SampleStream`
   Time-series for one channel; в Artisan это сейчас параллельные массивы `timex/temp`.

5. `DerivedMetric`
   RoR, AUC, phase stats, summary metrics; в Artisan часть live, часть saved in `computed`.

6. `Event`
   Лучше как structured objects вместо четырех параллельных массивов `specialevents*`.

7. `Annotation`
   Отдельно от roast events; в Artisan позиции аннотаций уже хранятся отдельно.

8. `OperatorAction`
   Отдельно от machine event values.

9. `MachineSnapshot` / `ControlSnapshot`
   Отделить от UI settings; в Artisan это сейчас размазано между sample arrays, extra devices, alarms и profile fields.

## Table 1 — `.alog` implementation map

| Компонент | Где найден | Роль | Чтение / запись / и то и другое | Насколько связан с UI |
| --- | --- | --- | --- | --- |
| `serialize()` / `deserialize()` | `src/artisanlib/util.py:973-986` | Low-level file I/O for `.alog` | И то и другое | Низко |
| `ProfileData` | `src/artisanlib/atypes.py:128-240` | Persisted schema for `.alog` payload | И то и другое | Средне, потому что schema already includes UI/config fields |
| `fileLoad()` / `loadFile()` | `src/artisanlib/main.py:13614-13658` | UI entry point and load orchestration | Чтение | Высоко |
| `loadbackground()` | `src/artisanlib/main.py:14182-14340` | Reads `.alog` into background comparison state | Чтение | Высоко |
| `setProfile()` | `src/artisanlib/main.py:15721-16434` | Hydrates persisted dict into runtime/UI state | Чтение | Очень высоко |
| `computedProfileInformation()` | `src/artisanlib/main.py:16704-17011` | Builds saved summary/derived block | Запись | Средне-высоко |
| `getProfile()` | `src/artisanlib/main.py:17013-17231` | Materializes persisted profile dict from runtime/UI state | Запись | Очень высоко |
| `fileSave()` | `src/artisanlib/main.py:17313-17348` | UI entry point and save orchestration | Запись | Высоко |
| `fileConvertFrom()` | `src/artisanlib/main.py:17503-17538` | External format import -> `ProfileData` -> `.alog` | Запись `.alog` | Высоко |
| `fileConvert()` | `src/artisanlib/main.py:17552-17584` | `.alog` -> runtime -> export to other formats | Чтение `.alog` | Высоко |

## Table 2 — Roast data model map

| Сущность | Где найдена | Runtime / persisted / derived | Что хранит | Комментарий |
| --- | --- | --- | --- | --- |
| `tgraphcanvas` / `self.qmc` | `src/artisanlib/canvas.py:203`, `src/artisanlib/canvas.py:252` | Runtime | Почти весь roast/session/UI state | Фактический god-object |
| `timex`, `temp1`, `temp2` | `src/artisanlib/canvas.py:17956`, `src/artisanlib/atypes.py:206-208` | Runtime + persisted | Main sample streams | `temp1`/`temp2` semantically ET/BT at sampling layer |
| `extratimex`, `extratemp1`, `extratemp2` | `src/artisanlib/main.py:15753-15858`, `src/artisanlib/atypes.py:225-227` | Runtime + persisted | Extra channel streams | Shape tied to configured extra devices |
| `timeindex` | `src/artisanlib/canvas.py:7812`, `src/artisanlib/main.py:16710-16766` | Runtime + persisted | Landmark indices for CHARGE/DRY/FC/SC/DROP/COOL | Хорошая domain concept |
| `specialevents*` arrays | `src/artisanlib/canvas.py:8035-8038`, `src/artisanlib/main.py:16202-16208`, `src/artisanlib/main.py:17115-17118` | Runtime + persisted | Operator-facing events and values | Параллельные массивы, слабая модель |
| Annotation positions | `src/artisanlib/main.py:16344-16348`, `src/artisanlib/main.py:17230-17231` | Runtime + persisted | Layout of annotations/flags | Отдельно от core events |
| `delta*`, `unfiltereddelta*`, smoothed arrays | `src/artisanlib/canvas.py:4614-4719`, `src/artisanlib/canvas.py:7806` | Runtime + derived | RoR and smoothing-related series | Не выглядят как стабильный persisted contract |
| `computed` | `src/artisanlib/main.py:16704-17011`, `src/artisanlib/main.py:17228` | Derived + persisted | Summary metrics of roast/profile | Полезно как derived snapshot, не как canonical raw data |
| Background profile arrays (`temp1B`, etc.) | `src/artisanlib/main.py:14182-14340` | Runtime | Comparison/reference profile | Полезная, но UI-driven separation |
| `ProfileData` | `src/artisanlib/atypes.py:128-240` | Persisted | Full saved profile representation | Содержит и domain data, и UI/config |

## Table 3 — Recommendation for new architecture

| Элемент Artisan | Оставить как идею / compatibility layer / переосмыслить / переписать | Почему |
| --- | --- | --- |
| `ProfileData` as file compatibility boundary | Compatibility layer | Удобная опорная точка для импорта/экспорта `.alog`, но не стоит делать ее canonical model |
| `timeindex` landmarks | Оставить как идею | Четкая domain concept for roast milestones |
| Raw sample arrays for channels | Оставить как идею | Ясное разделение raw time-series from derived metrics |
| `computed` summary block | Оставить как идею | Хорошо отделяет summary from raw series, если держать его вторичным derived layer |
| Foreground/background profile split | Оставить как идею | Полезно для compare/reference workflows |
| `tgraphcanvas` as state owner | Переписать | Слишком много ответственности и coupling to UI |
| `specialevents`, `specialeventstype`, `specialeventsStrings`, `specialeventsvalue` | Переписать | Параллельные массивы хуже структурированных event objects |
| `.alog` as Python-literal serialization | Переписать | Слабая спецификация и плохая основа для нового cross-platform compatibility contract |
| `getProfile()` / `setProfile()` monolith | Переосмыслить | Нужен explicit mapper between canonical model and compatibility formats |
| Export path via `setProfile()` + `redraw()` | Переписать | Export should not depend on UI render cycle |

## Open questions

1. Насколько стабилен `.alog` как межверсионный контракт.
   По коду видно много compatibility branches и legacy fields, но без набора реальных `.alog` разных версий нельзя строго оценить backward/forward compatibility risk.

2. Какие именно поля export/import dumpers реально требуют уже пересчитанных `delta` arrays.
   Код `fileConvert()` явно делает `self.qmc.redraw()` перед export (`src/artisanlib/main.py:17569-17574`), но для точной карты по каждому exporter нужно отдельное чтение каждого dumper module.

3. Можно ли воспроизвести весь смысл `specialeventstype` и `specialeventsvalue` без полной матрицы etype semantics.
   В этом проходе прослежены storage и call chains, но не проведена полная семантическая декомпозиция всех event type codes.

4. Насколько безопасно делать round-trip `.alog` export, если новый продукт не будет хранить UI/style/alarm-specific fields.
   По коду видно, что `.alog` включает их, но не строго доказано, какие из них критичны для “good enough” round-trip compatibility без набора golden files.
