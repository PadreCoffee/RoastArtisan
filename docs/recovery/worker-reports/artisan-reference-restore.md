# Worker report: Artisan reference selection restore

Branch: `fix/artisan-reference-restore`
File touched: `src/artisanlib/roast_properties.py` (only)

## The bug

When a roast has a cloud **reference** selected, reopening the Roast Properties
dialog showed the reference combo as **«Без эталона»** instead of the saved
reference. Downstream this could drop the reference on save, after which the
cloud falls back to the last roast of the coffee as the chart underlay.

## Root cause (verified by code reading)

The reference is modelled entirely as `qmc.backgroundUUID`:

- The dialog seeds its selection from it — `roast_properties.py:629`
  `self.template_uuid = self.aw.qmc.backgroundUUID if ... else None`.
- The upload payload is built from it — `plus/roast.py:412`
  `if aw.qmc.backgroundUUID: d['template'] = {'id': aw.qmc.backgroundUUID}`.
  When `backgroundUUID` is falsy, **no `template` field is sent at all**, and the
  backend treats the upload as authoritative and clears the roast's reference.

The combo is populated asynchronously by
`plus.stock.getReferencesFromAPI(coffee_hr_id, blend_hr_id, machine)`, whose
results are filtered server-side by coffee/blend/machine. A reference can
legitimately be **absent** from that filtered list (e.g. it belongs to a
different coffee, or the bean is linked via `green_bean_id` rather than
`coffee_id`). In `_applyTemplatesToCombo` the previous code only re-selected the
saved reference if its uuid appeared in the fetched list; otherwise the combo
fell back to index 0 = «Без эталона». It already *retained* `template_uuid` in
that case (unless the user changed coffee/blend), so the auto-wipe was partly
mitigated — but the **selection was invisible**, which is misleading and leaves
the reference one stray combo interaction away from being lost.

So the residual defects were:
1. **Display:** a retained reference not returned by the filtered fetch was not
   shown as selected (`_applyTemplatesToCombo`, ~line 2520).
2. **Robustness on save:** `accept()` (~line 5998) loaded from `template_uuid`
   and explicitly cleared the background when `template_uuid` became `None`, but
   had no guard to keep `backgroundUUID` populated when a reference was still
   selected yet its profile could not be (re)loaded.

## Fix (narrow, `roast_properties.py` only)

(a) **Seed a display label** for the already-selected reference at construction
time (`_referenceDisplayLabel()`, built from the loaded background's
`titleB` / batch number, falling back to `uuid[:8]`). Stored in
`self.template_label`.

(b) **Inject the retained reference** into `_applyTemplatesToCombo`. If a
reference is selected but its uuid is not in the (coffee/blend/machine-filtered)
fetch result, and the user did **not** change the coffee/blend, the reference is
prepended to the template list as `{'uuid', 'label', '_raw': {}}` so it stays
**visible and selected** instead of collapsing to «Без эталона». The existing
"user changed coffee/blend → drop the reference" behaviour is preserved
unchanged.

(c) **Guard `accept()`** with one extra branch: if a reference is still selected
(`template_uuid is not None`) but `loadbackgroundUUID(...)` could not load it as a
background and `qmc.backgroundUUID` is out of sync, set
`qmc.backgroundUUID = self.template_uuid`. This guarantees the upload still
carries `template = {'id': <uuid>}` and the cloud does not wipe the reference.
It runs only for a genuinely-selected reference (never after an explicit clear,
which is handled by the preceding branch).

The upload protocol (`plus/roast.py` `template` payload shape) was **not**
touched.

## How a save now keeps the reference

1. Dialog opens on a referenced roast → `template_uuid` seeded from
   `backgroundUUID`; `template_label` captured from the loaded background.
2. Async fetch returns a filtered list that may omit the reference →
   `_applyTemplatesToCombo` injects it → combo shows the reference as selected.
3. User clicks OK without touching the combo → `templateSelectionChanged` never
   fires → `template_uuid` unchanged.
4. `accept()` → `loadbackgroundUUID(template_file, template_uuid)` reloads the
   reference and sets `backgroundUUID`; if that load fails, the new guard sets
   `backgroundUUID = template_uuid` anyway.
5. `plus.queue.addRoast()` builds `d['template'] = {'id': backgroundUUID}` → the
   reference is preserved on the cloud.

## What I verified

- **Static / reasoning** (no headless UI test exists for this Qt dialog):
  - `python3 -c "ast.parse(...)"` on the edited file → syntax OK.
  - Traced the data flow `template_uuid → loadbackgroundUUID → qmc.backgroundUUID
    → plus/roast.py buildRoastPayload → d['template']`.
  - Confirmed combo index/`plus_templates` stay aligned after injection
    (index 0 = «Без эталона», index 1 = injected reference, then fetched items;
    `templateSelectionChanged` maps index `n` → `plus_templates[n-1]`).
  - Confirmed the injected item's empty `_raw` is handled gracefully by
    `_getReferenceSnapshot` (returns `None` → snapshot shows «—»), no crash.
  - Confirmed the new `accept()` branch only runs for a still-selected reference
    and never after an explicit user clear (handled by the preceding `elif`).
- **Not** verified: a live run of Artisan reopening the dialog against the prod
  cloud (no plus account / GUI session available in this environment).

## Note on a deeper, out-of-scope cause

The reference lives only in `qmc.backgroundUUID`. On loading a foreground
profile, the background/reference is restored in `main.py:16476-16503`, gated on
`'backgroundpath' in profile and ... != ''`. A profile saved with a
`backgroundUUID` but an empty/stale `backgroundpath`, or one whose reference is
not cached locally, can reach the dialog with `backgroundUUID` already `None`.
That path is outside this narrow fix and was left unchanged, but it is the place
to harden next if reference loss is ever observed *without* the combo ever having
shown the reference.
