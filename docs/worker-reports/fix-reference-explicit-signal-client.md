# Worker report — fix/reference-explicit-signal-client

**Branch:** `fix/reference-explicit-signal-client` (worktree `../artisan-ref-signal`, off `master` @ `d93edde3c`)
**Pairs with:** backend branch `fix/reference-explicit-signal-backend` (deploy together).

## Scope

The `/aroast` upload sent `template: {id: <backgroundUUID>}` for **any** loaded background.
The patched backend creates a reference (эталон) link only when the payload carries
`template.is_reference == true`. Per owner canon **manual background ≠ reference**, so the
client must send `is_reference: true` **only** when the background was chosen via the cloud
reference selector — never for a manually loaded file or a recent/past roast.

This change tracks how the current background was loaded and emits the `is_reference` flag
accordingly. No refactor of the background/sync architecture; no dependency changes; the
success path and the profile-curve upload are untouched.

## Key changes per file

### `src/artisanlib/canvas.py` (`tgraphcanvas.__init__`)
- New state `self.backgroundIsReference: bool = False` (alongside `backgroundUUID`). This is the
  single source of truth consumed by the uploader. Default **False** → nothing is a reference
  until explicitly flagged.

### `src/artisanlib/main.py`
- `loadbackground(filename)` (the one funnel for **every** background load — manual file, recent
  roast, scheduler, and the reference selector via `loadbackgroundUUID`): sets
  `self.qmc.backgroundIsReference = False` on the single success path, paired with the existing
  `backgroundUUID` assignment. Every load therefore defaults to non-reference; the reference
  selector re-flags it True **after** the load returns.
- `deleteBackground()`: clears `backgroundIsReference = False` along with `backgroundUUID`.

### `src/artisanlib/roast_properties.py` (`editGraphDlg`)
- New dialog field `self.template_is_reference: bool`, seeded in `__init__` from the **current**
  background's `backgroundIsReference`. This preserves the existing reference status when the user
  opens Roast Properties and accepts without changing the selector.
- `templateSelectionChanged(n)` (the cloud-reference combo handler): sets
  `template_is_reference = (template_uuid is not None)` — a chosen entry is a genuine reference,
  «Без эталона» clears it.
- `recentRoastActivated(n)` (title-field recent/past-roast picker): sets
  `template_is_reference = False` — a past roast is not a reference even though it also writes
  `template_uuid`.
- `accept()`:
  - Branch where the background (re)loads (`loadbackgroundUUID(...)` returns True): sets
    `aw.qmc.backgroundIsReference = self.template_is_reference` (was previously planned as
    `template_uuid is not None`).
  - Branch where a reference id is preserved but the curve could not (re)load: sets
    `aw.qmc.backgroundIsReference = self.template_is_reference` (was previously hardcoded `True`).

### `src/plus/roast.py` (`getRoast`)
- After `d['template'] = {'id': aw.qmc.backgroundUUID}`, add
  `if getattr(aw.qmc, 'backgroundIsReference', False): d['template']['is_reference'] = True`.
  Manual/file/recent-roast backgrounds keep the bare `{id}` shape (unchanged behaviour).

## Important findings — exact load-path flag logic

Tracing every writer of the flag and every caller of the loaders:

- **`backgroundIsReference` is consumed in exactly one place:** `plus/roast.py:getRoast`, guarded
  by `if aw.qmc.backgroundUUID`. So the flag only matters when a background UUID is present.
- **`loadbackground()` is the single load funnel.** All callers route through it: manual "Load
  Background" (`background.py:865`), comparator (`comparator.py`), recent-roast menu
  (`main.py:5730` → `loadAndRedrawBackgroundUUID` → `loadbackgroundUUID`), scheduler
  (`schedule.py:1656` → same), restore-on-reset, and the reference selector. Every one of them
  sets the flag **False** inside `loadbackground`. Only the reference selector re-flags True
  afterwards. → **reference selector → True; everything else → False.** ✓
- **Critical subtlety in Roast Properties:** `template_uuid` is written by **two** different UI
  actions — the cloud-reference combo (`templateSelectionChanged`) **and** the title-field
  recent-roast picker (`recentRoastActivated`, wired at `titleedit.activated`, line 843) — and it
  is additionally **seeded at `__init__` from `backgroundUUID`** and can survive combo refetches
  via injection (`_applyTemplatesToCombo`). Therefore a naive `template_uuid is not None` test in
  `accept()` would have **mis-flagged two non-reference cases as references**:
  1. A recent/past roast picked from the title field (it sets `template_uuid` from `roastUUID`).
  2. A pre-existing **manual** background re-saved by merely opening Roast Properties and clicking
     OK (init seeds `template_uuid = backgroundUUID`; the combo can inject+reselect it; the accept
     branch reloads it and would flip the flag True).
  The dedicated `template_is_reference` field, seeded from the real current status and only set
  True by the reference combo, eliminates both. `template_is_reference` is only read when
  `template_uuid` is non-None, and it is assigned at every site that assigns a non-None
  `template_uuid` (`__init__` seed, `templateSelectionChanged`, `recentRoastActivated`), so it is
  always consistent at the point of consumption.

## Watch-outs

- The flag is intentionally **client-local UI state**; it is not persisted in the `.alog` profile
  and not restored on profile load. That is correct for the contract — "is reference" is a
  property of *how this session selected the background*, not of the saved roast. A background
  restored from a reopened profile defaults to non-reference until reselected via the cloud
  selector.
- This pairs with the backend: the client now sends `template.is_reference == true` only for
  genuine references; the backend must create the reference link only on that flag. They must
  deploy together — until the backend ships, the extra key is simply ignored by the old server.
- `getRoast` uses `getattr(..., False)` defensively so the uploader is safe even against an older
  `qmc` lacking the attribute.

## Flags

- None blocking. One judgement call: I extended the Roast-Properties tracking beyond the minimal
  `template_uuid is not None` test because tracing showed that test would re-introduce the very
  bug being fixed (manual/past-roast → flagged as reference). This stays within "surgical" — one
  new boolean plus its assignments, no architectural change.

## Verification

- `git diff --check` → clean (exit 0, no whitespace errors).
- `py_compile` (doraise) on each touched file → **OK** for
  `canvas.py`, `main.py`, `roast_properties.py`, `plus/roast.py`.
- Existing tests: `src/test/unitary/plus/test_roast.py` is the only suite covering the touched
  upload code. It **fails at collection** with
  `TypeError: unsupported operand type(s) for |: 'Mock' and 'NoneType'` at `plus/roast.py:259`
  (`def trimBlendSpec(...)->stock.Blend|None`) — a **pre-existing** Python 3.13 incompatibility
  (the module is imported with `plus.stock` mocked, and PEP 604 `X|None` annotations on a `def`
  evaluate eagerly without `from __future__ import annotations`). **Verified identical failure
  with the original, unmodified `roast.py` stashed** → not a regression from this change. No
  background-loader test exists.
- Manual test the owner should run:
  - (a) Select a cloud reference in Roast Properties → confirm the `/aroast` payload has
    `template.is_reference == true`.
  - (b) Manually load a background (file) or pick a recent/past roast → confirm the payload has
    **no** `is_reference` key → the cloud does not mark the roast by-reference.
  - (c) Open Roast Properties on an existing manual background and click OK without touching the
    reference combo → confirm the payload still has **no** `is_reference` key.

## Merge readiness

Code-complete and self-consistent; compiles; whitespace-clean; the only relevant test failure is
pre-existing and environmental, proven not caused by this change. Pairs with
`fix/reference-explicit-signal-backend` — **deploy together**. Recommend the owner run the manual
payload checks (a/b/c) before merging. **Not merged** — awaiting explicit owner go-ahead.
