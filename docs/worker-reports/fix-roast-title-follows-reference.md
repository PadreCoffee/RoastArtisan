# Roast title must follow the selected reference — TITLE-2

Branch: `fix/roast-title-follows-reference`. Merged into `master` with `--no-ff`.

## Reported symptom
"Selecting a reference (эталон) used to retitle the current roast to the reference's title, but it
stopped doing that."

## Required behaviour (confirmed with the user)
1. Open Roast Properties, pick a reference → the roast title becomes the reference title.
2. Reopen and type a title by hand → the typed title stays.
3. Pick a reference again → the roast title becomes the reference title again.

## Root cause (two defects, both reproduced by failing tests before the fix)

`src/artisanlib/roast_properties.py`, class `editGraphDlg`:

1. **The reference title was reverted to the coffee/blend name (regression of `28fc81bb6`).**
   That commit introduced `last_auto_title` — the string the dialog last auto-applied — and made
   `_titleIsAutoDerived()` treat it as overwritable. `_applyAutoTitle()` is shared by the
   coffee/blend path and the reference path, so a title taken from a reference landed in
   `last_auto_title` too. Any later `populatePlusCoffeeBlendCombos()` — stock-worker
   `updatedSignal` (`roast_properties.py:1791`), weight-unit change, bean-label-format change,
   store change — calls `updateTitle()`, which then found `current == last_auto_title` and
   overwrote the reference title with the coffee lot label. Before `28fc81bb6` the reference title
   was not in the overwritable set and survived every repopulate.

2. **A reference could not replace a title that came from an earlier reference.**
   `_setTitleFromReference()` only wrote when `_titleIsAutoDerived()` said yes, and that check only
   recognises coffee/blend-derived titles (plus `last_auto_title`, which is empty after a reload).
   So on a reopened roast whose saved title was a reference name, the title looked "user-typed" and
   picking another reference did nothing — exactly the reported symptom, permanent once the user's
   roasts carried reference-derived titles. Present since `872588151` (the feature's origin).

3. **Re-picking the already-selected reference did nothing** — `currentIndexChanged` does not fire
   for an unchanged index, so the title could not be restored after a manual edit without going
   through another entry first.

## Changes (`src/artisanlib/roast_properties.py`)
- **`reference_auto_title`** (`roast_properties.py:1344`): the title currently taken from the
  selected reference, tracked separately from `last_auto_title`.
  `_applyAutoTitle(title, *, from_reference=False)` maintains it; any non-reference auto-title
  clears it.
- **`_titleIsAutoDerived()`** returns `False` when the current text equals `reference_auto_title`
  — a reference is chosen explicitly and outranks the coffee/blend auto-derivation, so
  `updateTitle()` can no longer revert it (defect 1).
- **`_setTitleFromReference()`** is now unconditional: picking an entry in the reference combo is an
  explicit user action and always retitles the roast (defect 2). A title typed *after* that is no
  longer the reference title, so the existing custom-title protection applies to it again
  (requirement 2).
- **`templateReactivated()`** on the combo's `activated` signal re-applies the reference title when
  the user re-picks the entry that is already selected (defect 3). Idempotent on a real index
  change; ignores index 0.
- **Clearing the reference** («Без эталона») falls back to the coffee/blend auto-title when the
  title still shows the cleared reference's name, so a stale reference name is not sent to the
  cloud. A hand-typed title is left alone.
- **Seeding** (`roast_properties.py:1768`): if the loaded title equals the loaded reference's
  display label, it is remembered as reference-derived so it keeps outranking the coffee/blend
  auto-title across dialog sessions.

Trade-off accepted by the user: picking a reference now also replaces a hand-typed title. It is an
explicit gesture, and typing a new title afterwards is protected from every automatic refresh.

## Cloud
Unchanged path: the title is mapped to `label` in `plus/roast.py` and is part of
`sync_record_attributes`, so a title-only change re-syncs on the final OFF update.

## Tests
`src/test/unitary/artisanlib/test_roast_title_refresh.py` — 13 → 22 tests. New coverage:
the reported bug in both strands, the full three-step user flow, re-picking the same reference,
clearing the reference (with and without a custom title), and a title typed after the reference.
`test_reference_never_overwrites_custom_title` was replaced by
`test_reference_overwrites_custom_title`, which encodes the new intent.

Verification: `python3 -m pytest test/unitary -q` → 2286 passed, 53 failed, 3 skipped. The 53
failures are the pre-existing baseline in `test/unitary/plus` (identical set on `HEAD` before the
change, checked via `git stash`). `ruff check` reports only the 3 pre-existing `E702` in untouched
lines.
