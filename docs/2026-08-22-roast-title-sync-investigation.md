# Roast-title / reference-sync investigation — C56

**Type:** investigation only. No runtime code was changed. No refactor.
**Repo:** `PadreCoffee/RoastArtisan` (this checkout), branch `master` @ `2df53190b`
(the merge of `fix/roast-title-follows-reference`, i.e. **TITLE-2 is present in the code I read**).
**Date:** 2026-08-22.

All line references are to `src/artisanlib/roast_properties.py` unless another file is named.

---

## Scope

Explain, against the current client code, why:
- the roast title does not follow the selected coffee/reference (owner: "selecting a reference
  does not change the title in the client AT ALL");
- the batch weight has "the same problem";
- a manual rename does not survive to the cloud;
- opening Roast Properties re-fetches and can silently reset the reference to «Без эталона».

And propose (not implement) a minimal fix for the owner's three title rules plus the dialog reset.

The cloud side is taken as already established (references delivered with the name in
`reference_name` / `reference_binding.reference_name` / `reference_entity.title`; `POST /aroast`
stores the client's `title` verbatim; the single 404 and the missing `POST /aroast` in the run
are expected). This report does not re-derive any of that.

---

## Reproduction

**Code-only reading — labelled as such.** I did **not** run the client GUI end-to-end. A faithful
repro needs a live Roastlocal Cloud plus-account, stock with coffees that carry references, a
completed cloud roast, and the Qt GUI — none of which is available in this environment. What I did
run/inspect:

- Static reading of `editGraphDlg` (title + reference + weight paths) and of `plus/stock.py`
  (`getReferencesFromAPI`) and `plus/roast.py` (upload mapping).
- The existing regression suite `test/unitary/artisanlib/test_roast_title_refresh.py` (22 tests,
  added by TITLE-1/TITLE-2). These bind the **real** `editGraphDlg` methods and assert the
  title-decision logic; they are the closest thing to a repro I could exercise. They exercise the
  decision helpers and the reference handler **by calling them directly** — they do **not** drive
  the live Qt `currentIndexChanged`/`activated` signals, and they do **not** exercise the async
  `_applyTemplatesToCombo` auto-selection path. That gap is exactly where the live bug lives (see
  Root cause).

Because I cannot run the GUI, every behavioural claim below is grounded in a cited line, or marked
UNVERIFIED.

---

## Findings

### 1. WHERE the roast title is produced, and WHEN it is fixed

The title lives in one editable combo, `self.titleedit` (a `RoastsComboBox`), created seeded from
the profile title at **`roast_properties.py:847`** (`RoastsComboBox(self, self.aw, selection =
self.aw.qmc.title)`). Its text is written at exactly these moments:

- **At dialog open (seeding of the tracker, not the text):** `1766–1772`. The loaded title is
  classified as auto-derived (`last_auto_title`) if it equals `_autoTitleCandidate()`, or as
  reference-derived (`reference_auto_title`) if it equals the loaded reference label.
- **On a completed roast, during the initial/again populate:** `populatePlusCoffeeBlendCombos`
  calls `updateTitle(...)` explicitly for the coffee branch (`2175`) and blend branch (`2224`) —
  the TITLE-1 decoupling.
- **On a user coffee/blend selection:** `coffeeSelectionChanged` → `fillCoffeeData` →
  `updateTitle` (`2417`); `blendSelectionChanged` → `fillBlendData` → `updateTitle` (`2373`).
  `updateTitle` (`2324`) applies `_autoTitleCandidate()` (`2282`) — the **coffee lot label** or
  the blend label, never a reference name.
- **On a reference pick (эталон combo):** `templateSelectionChanged` (`2667`) →
  `_setTitleFromReference` (`2708`) → `_applyAutoTitle(..., from_reference=True)` (`2314`).
- **On a recent/past-roast pick (title-field dropdown):** `recentRoastActivated` (`2958`) →
  `_applyAutoTitle(rr['title'])` (`2965`).
- **Committed to the model at OK:** `accept()` sets `self.aw.qmc.title = ' '.join(
  self.titleedit.currentText().split())` at **`6049`** — i.e. verbatim whatever the widget shows.
- **Sent to the cloud:** `plus/roast.py:149` maps profile `title` → payload `label`. The client
  never derives a title server-bound; the cloud stores what the widget held at OK.

So the title is *fixed* into `qmc.title` **at OK**, from the widget text, and the widget text is
last touched by whichever of the handlers above fired last. There is **no** title computation at
upload time.

### 2. WHY changing the coffee/reference does not recompute the title — and the weight

**The reference→title link is driven ONLY by user-interaction signals, and the automatic path is
signal-blocked.** `_setTitleFromReference` is reachable from exactly two slots:
`templateSelectionChanged` (wired to the combo's `currentIndexChanged`, `1467`) and
`templateReactivated` (wired to `activated`, `1468`). Every *programmatic* change to that combo —
`_applyTemplatesToCombo` (`2633`), which is the path that runs when a coffee is selected and its
references arrive — sets the current index **inside `blockSignals(True)`** (`2650`, index set at
`2661`, unblocked at `2663`). With signals blocked, neither slot runs, so `_setTitleFromReference`
is never called from an automatic selection. **Result: when the reference is selected for you (by
selecting a coffee), the title does not change.**

**There is no default-reference auto-selection at all.** In `_applyTemplatesToCombo`, `selected_idx`
is computed **only** by matching an already-known `self.template_uuid` (`2655–2660`). For a freshly
selected coffee, `template_uuid` is either `None` or the *previous* coffee's reference, so
`selected_idx` stays `0` → «Без эталона». The coffee's default reference is never selected, so even
the (blocked) selection would not land on it.

**On a user coffee/blend change the previously chosen reference is actively cleared** (see Finding 4)
and the title path used is `updateTitle` → `_autoTitleCandidate` (`2282`), which yields the coffee
**lot label**, not the reference name. So after a coffee switch the title, at best, follows the new
coffee's lot label; it never follows a reference. Whether it even follows the coffee depends on
`_titleIsAutoDerived` (`2292`): if the current title equals `reference_auto_title` it is treated as
reference-owned and left untouched (`2299–2302`), which can leave a stale name in place.

**Weight — DIFFERENT cause (a missing feature, not the signal-block).** No code copies a coffee's or
a reference's batch size into the weight field on a coffee/reference change:
- `checkWeightIn` (`5565`) only sets **stylesheet colour** based on available stock amount
  (`5597–5604`); it never writes a weight value.
- `coffeeSelectionChanged`/`blendSelectionChanged` call `checkWeightIn` only (`2482`, `2541`);
  they do not set `weightinedit`.
- `templateSelectionChanged` (the эталон combo) never touches the weight field at all.
- The **only** place a weight is copied from a "reference-like" source is `recentRoastActivated`
  (`2967`, `self.weightinedit.setText(f"{rr['weightIn']:g}")`) — the **title-field recent/past-roast
  picker**, which is a different control from the эталон combo.

So the batch weight not following the эталон is not the same bug as the title: the title has a
(signal-blocked) reference→title mechanism; the weight has **no** reference→weight mechanism to
block. They do not share a cause.

### 3. WHY a manual rename does not survive

Within one dialog session, a manual rename **is** preserved: `accept()` reads the widget verbatim
into `qmc.title` (`6049`), and `_titleIsAutoDerived` (`2292–2312`) protects a user-typed string —
it is overwritable only if empty/«Roaster Scope», equal to `last_auto_title`, or equal to a
previous coffee/blend label (or its lot form). A genuinely typed name matches none, so the coffee/
blend auto-refresh in `updateTitle` leaves it alone.

Two ways a hand-typed name is still lost, both in current code:

- **Picking a reference after typing overwrites the typed name — by design.**
  `_setTitleFromReference` (`2708`) is **unconditional** (TITLE-2, defect 2 fix): it always calls
  `_applyAutoTitle`.
  Its own docstring states the trade-off ("A title typed AFTER this still survives every automatic
  coffee/blend refresh; only picking another reference replaces it again"). This directly conflicts
  with the owner's rule 3 if the owner expects a post-selection manual edit to win over a *later*
  reference pick. It does not conflict for the coffee/blend refresh case.
- **The cloud-carries-the-wrong-name claim is not reproduced from the client code.** The upload path
  faithfully carries `qmc.title` → `label` (`plus/roast.py:149`). In the captured run the owner did
  **not** upload (no `POST /aroast`), so "the cloud still receives the wrong name" cannot be from
  that run. It is either (a) a stale name that was already in the widget at OK because an auto-path
  had overwritten the manual edit, or (b) an observation from a build that predates TITLE-1/TITLE-2.
  I could not find a client path that discards a hand-typed title *at* OK. **UNVERIFIED / needs a
  live upload trace** (see Open questions).

### 4. WHY opening the dialog re-fetches and can reset the reference to «Без эталона»

**The re-fetch on open is real and happens up to three times.** Opening the dialog runs
`populatePlusCoffeeBlendCombos()` synchronously (`1774`), and then schedules a stock refresh:
`self.stockWorker.updatedSignal.connect(self.populatePlusCoffeeBlendCombos)` (`1800`) +
`QTimer.singleShot(10, plus.stock.update)` (`1801`). Each `populatePlusCoffeeBlendCombos` ends with
`populateTemplateCombo()` (`2233`), which re-issues `GET /roasts/references` (`2588–2602`). Add the
per-coffee re-fetch on selection and you get the "same coffee queried three times" seen in the log.

**The exact code paths that clear the reference to «Без эталона»:**

- **No coffee/blend in context → hard clear.** `populateTemplateCombo` (`2576–2587`): if neither
  `plus_coffee_selected` nor a blend spec is set, it unconditionally does `self.template_uuid = None`
  (`2578`), shows only `'Без эталона'` (`2583`) and disables the combo (`2584`) — **even though a
  reference/background was loaded and `template_uuid` was seeded from `qmc.backgroundUUID` at `630`.**
  This fires on open for any roast that has a reference/background but no `plus_coffee`/`plus_blend`
  selection saved (e.g. beans entered as free text).
- **User changed coffee/blend and the saved reference is not in the new fetch → clear.**
  `_applyTemplatesToCombo` (`2639–2643`): if `template_uuid` is set, is absent from the fetched
  list, **and** `self.user_updated_coffee_or_blend` is True (set at `2450`/`2500`), it drops
  `template_uuid`/`template_file` → combo collapses to index 0 «Без эталона».

**The guard that prevents a reset on a *pure* open** is `_applyTemplatesToCombo` `2644–2648`: when
the user has **not** changed the coffee/blend, a saved-but-missing `template_uuid` is *injected*
back into the list and kept selected instead of collapsing. So a clean open with a saved
`plus_coffee` context should retain the reference. If the owner still sees a reset on a pure open,
the trigger is almost certainly the **no-coffee/blend hard-clear** (`2576–2587`) or a
`template_uuid` normalisation mismatch (seeded raw from `backgroundUUID` at `630`, compared against
`util.normalizeUUID`-normalised fetch ids at `2639`/`2656`) — **UNVERIFIED, needs the owner to say
whether the affected roasts carry a saved `plus_coffee`.**

### 5. What the client does with `reference_name` / `reference_entity.title` today

`plus/stock.py:getReferencesFromAPI` (`1805`) reads `data.items` (`1817`) and normalises each item
in `_parseReferenceItems` (`1791`):

```python
label = (item.get('reference_name') or item.get('title') or '').strip() or normalized[:8]   # 1800
```

- It reads the **top-level** `reference_name`, then top-level `title`, else falls back to the first
  8 hex chars of the UUID. Given the cloud does send top-level `reference_name`, the client should
  get the real name here.
- It **does not** read `reference_binding.reference_name` or `reference_entity.title` — the two
  other places the cloud carries the same name. If a future/edge payload omits top-level
  `reference_name` **and** `title`, the label silently degrades to a hex prefix rather than using
  the nested copies. (Fragility, not the reported bug.)

The label then flows: `_parseReferenceItems` → `plus_templates` items → combo item text (`2654`) →
`templateSelectionChanged` reads it back as `reference_label` (`2676`) → `_setTitleFromReference`.
So the name **is** read and **is** wired to the title — but, per Finding 2, only when the combo is
changed by a **user** gesture, never when it is populated/auto-selected programmatically.

---

## Root cause

Ranked candidates. The top two are proven from the code; the third is the contradiction that must
be surfaced.

**C1 (proven) — the automatic reference→title substitution the owner wants (rule 2) is not
implemented; the one mechanism that could do it is signal-blocked.** `_setTitleFromReference` is
only reachable from `currentIndexChanged`/`activated` (user gestures). The programmatic
auto-selection in `_applyTemplatesToCombo` runs under `blockSignals(True)` (`2650`/`2661`/`2663`),
so selecting a coffee (which loads its reference) never retitles. This fully explains "selecting a
reference does not change the title AT ALL" under the natural reading that the reference is chosen
*for* the operator by selecting the coffee.

**C2 (proven) — even unblocked, no default reference would be selected.**
`_applyTemplatesToCombo` only re-selects an already-known `template_uuid` (`2655–2660`); a fresh
coffee's default reference is never chosen (`selected_idx` stays 0), and a coffee change actively
clears the prior reference (`2639–2643`). So rule 2 needs both (a) picking the coffee's default
reference and (b) emitting the title update.

**C3 (contradiction — must be reported, not resolved) — for a *manual* эталон pick, the current
merged code DOES retitle.** `templateSelectionChanged` (`2687–2688`) calls the unconditional
`_setTitleFromReference` (`2708–2714`); `MyQComboBox` (`widgets.py:45`) is a plain `QComboBox` whose
`currentIndexChanged` fires on a manual pick; and `test_roast_title_refresh.py` asserts this logic.
So "does not change AT ALL" contradicts the code **iff** the owner means a manual pick from the
эталон dropdown. Discriminators (for the owner to run):
1. After switching coffee, does the эталон combo show real reference names, or «Без эталона» /
   a hex string / an empty disabled combo? (Distinguishes C1/C2 from an empty-fetch problem.)
2. If real names are shown, does opening the dropdown and clicking a **named** reference change the
   title? **Yes →** the gap is purely the automatic path (C1/C2). **No →** either the running build
   predates the TITLE-2 merge (Aug 7) or the fetch returns 0 items so there is nothing to pick.
3. Report the running build's version/date, to rule the old-build case in or out.

**Weight** is a separate root cause: there is simply no reference→weight (or coffee→weight) copy in
the code; only the title-field recent-roast picker copies weight (`2967`).

---

## Proposed fix (NOT implemented)

All in `src/artisanlib/roast_properties.py` unless noted. Minimal, no architecture change.

**Owner rule 1 — no coffee selected → free-text title.** Already satisfied: with no coffee/blend,
`_autoTitleCandidate` returns «Roaster Scope» only, and `_titleIsAutoDerived` protects a typed
title. No change needed; keep as a regression test.

**Owner rule 2 — coffee selected + has a default reference → substitute the reference name
automatically, but only after the primary (coffee/blend) selection.** Two small changes:
1. In `_applyTemplatesToCombo`, when the coffee/blend was just changed by the user
   (`user_updated_coffee_or_blend`) and no reference is currently selected, choose the coffee's
   **default** reference instead of index 0. This needs a "default" signal from the payload — read
   an `is_default`/ordering field in `plus.stock._parseReferenceItems` (`plus/stock.py:1791`) and
   surface it on the normalised dict; if the backend does not mark a default, define the rule as
   "the first item" and confirm with the owner.
2. Make the auto-selection emit the title without unblocking the property-fill side effects: after
   `_applyTemplatesToCombo` sets the index under blocked signals, call `_setTitleFromReference(
   label_of_selected)` **explicitly** for the chosen reference (mirroring how TITLE-1 calls
   `updateTitle` explicitly in the blocked completed-roast branch at `2175`/`2224`). Do this only
   when a reference is actually auto-selected, so rule 1 and hand-typed titles are untouched.

**Owner rule 3 — a title edited by hand AFTER the selection must persist and not be overwritten.**
Current `_titleIsAutoDerived` already protects it against coffee/blend refreshes. The one conflict
is that a later reference pick overwrites it unconditionally (`_setTitleFromReference`, `2708`). If
the owner wants the post-selection manual edit to also survive a later reference pick, gate
`_setTitleFromReference` behind `_titleIsAutoDerived()` for the *manual re-pick* path while keeping
it unconditional for the *automatic rule-2* path — i.e. split "user re-picked the same/another
reference" from "system applied the default". This is a behavioural decision for the owner (it
reverses part of the TITLE-2 trade-off), so it must be confirmed before coding.

**Properties-dialog reset to «Без эталона».** Two guards:
1. In `populateTemplateCombo` (`2576–2587`), do **not** hard-clear `template_uuid` when there is a
   loaded reference/background just because no `plus_coffee`/`plus_blend` is in context. Preserve
   and inject the seeded `template_uuid` (as `_applyTemplatesToCombo` already does at `2644–2648`)
   instead of setting it to `None`.
2. Normalise the seed at `630` (`self.template_uuid = util.normalizeUUID(self.aw.qmc.backgroundUUID)`)
   so equality tests at `2639`/`2656` against normalised fetch ids cannot fail on format alone.

**Weight (owner: "same problem").** If the batch weight should follow the selected reference, add a
reference→weight copy analogous to the recent-roast path: when a reference is selected (and only
then), populate `weightinedit` from the reference's batch size delivered in the references payload.
This is a **new feature**, not a fix to existing wiring; confirm the owner actually wants the
current roast's green weight overwritten by the reference's.

---

## Open questions for the owner

1. **"Selecting a reference" = which gesture?** Selecting a *coffee* (reference chosen for you), or
   opening the эталон dropdown and clicking a named reference? The code behaves differently for the
   two (C1/C2 vs C3).
2. **Build version/date** of the client that shows the bug. Is it after the TITLE-2 merge
   (2026-08-07)?
3. After switching coffee, what does the эталон combo show — real names, «Без эталона», a hex
   string, or empty+disabled?
4. Do the affected roasts carry a saved `plus_coffee`/`plus_blend`, or beans-as-free-text? (Decides
   whether the `2576–2587` hard-clear is your reset path.)
5. Should a hand-typed title survive a **later** reference pick (reversing part of TITLE-2), or only
   survive coffee/blend refreshes?
6. Should the batch weight follow the reference at all, overwriting the current green weight?
7. Does the backend mark a **default** reference in the `/roasts/references` items (a field/order),
   so rule 2 can pick it deterministically?

---

## Confidence

- **Proven from code (high):** the title's write sites and the OK/upload path (Finding 1); the
  reference→title link is user-signal-only and the auto path is `blockSignals`-blocked (C1); no
  default-reference auto-selection and the coffee-change clear (C2); weight has no reference/coffee
  copy and only the recent-roast picker sets it (Finding 2, weight); the two reset-to-«Без эталона»
  code paths and the pure-open injection guard (Finding 4); the client reads only top-level
  `reference_name`/`title` and ignores the nested copies (Finding 5).
- **Inference (medium):** which of the reset paths the owner is actually hitting (Finding 4) — hinges
  on whether their roasts carry a saved `plus_coffee` and on UUID normalisation; and the mapping of
  the owner's "selecting a reference" onto C1/C2 vs C3.
- **Unverified (must flag):** "the cloud still receives the wrong name" — not reproducible from the
  client upload path (which carries `qmc.title` faithfully) and not from the captured run (no
  `POST /aroast`); needs a live upload trace or the running build's version (Finding 3, C3).
- **Contradiction (surfaced, not resolved):** the merged code retitles on a *manual* эталон pick,
  which contradicts "does not change AT ALL" unless the owner means the automatic case, an
  empty-fetch, or an older build (C3).

---

## Русское резюме для владельца

**Что ломается.** Название обжарки следует за эталоном **только** когда вы вручную выбираете эталон
в выпадающем списке. Когда эталон подставляется автоматически (после выбора кофе), название **не
меняется**: комбобокс эталона заполняется программно с заблокированными сигналами
(`_applyTemplatesToCombo`, строки `2650/2661/2663`), поэтому обработчик `templateSelectionChanged`,
который и переносит имя эталона в название, не вызывается. Плюс для нового кофе эталон по умолчанию
вообще не выбирается (`2655–2660`), а при смене кофе ранее выбранный эталон сбрасывается
(`2639–2643`). Итог правила «кофе → имя эталона в название автоматически» в коде нет.

**Вес партии — другая причина.** Вес не копируется из эталона нигде: `checkWeightIn` (`5565`) только
красит поле, а вес из «прошлой обжарки» берётся лишь в `recentRoastActivated` (`2967`) — это другой
список (поле названия), не селектор эталона. То есть это отсутствующая функция, а не та же ошибка.

**Ручное переименование.** Внутри диалога переименование сохраняется — на OK берётся текст поля как
есть (`6049`) и уходит в облако как `label` (`plus/roast.py:149`). Но повторный выбор эталона
перезаписывает набранное вручную имя намеренно (`_setTitleFromReference`, `2708`). Жалобу «в облако
уходит неверное имя» я по коду клиента не воспроизвёл: в зафиксированном логе выгрузки (`POST
/aroast`) не было. Нужен номер сборки и трасса реальной выгрузки.

**Сброс эталона при открытии.** Диалог перезапрашивает эталоны при каждом открытии (`1774` +
`1800–1801`, отсюда «тот же кофе три раза»). Сброс в «Без эталона» дают два места:
`populateTemplateCombo` `2576–2587` (когда нет выбранного кофе/бленда — жёсткий сброс, даже если
эталон был загружен) и `_applyTemplatesToCombo` `2639–2643` (после смены кофе пользователем).

**Во сколько обойдётся починка.** Небольшая, точечная правка в одном файле
(`src/artisanlib/roast_properties.py`), плюс одно поле в `plus/stock.py`:
1) при авто-выборе эталона после смены кофе — явно вызывать перенос названия (как TITLE-1 уже делает
для завершённой обжарки), и выбирать эталон по умолчанию; 2) не сбрасывать `template_uuid` в
`populateTemplateCombo`, когда эталон загружен, но кофе не выбран; 3) нормализовать UUID при
инициализации (`630`). Правки «переписывать ли вручную набранное имя при повторном выборе эталона» и
«должен ли вес следовать за эталоном» — это решения по продукту, нужен ваш ответ перед кодом.
Реализацию в этом чате не делал — это только отчёт.
