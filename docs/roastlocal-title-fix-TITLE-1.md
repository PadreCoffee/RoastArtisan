# Roast-title refresh on a completed roast — TITLE-1

Branch: `fix/roast-title-refresh-on-completed-roast` (own worktree). Not merged. Clean tree.

## Scope (one confirmed bug)
On a COMPLETED roast (CHARGE + DROP set), changing the coffee/blend and/or the reference (эталон)
did not refresh the roast title («Название»). The previous coffee's name stayed and was sent to
the cloud. Also required: a corrected title (manual or auto) must reach the cloud on the FINAL
update at OFF/reset.

## Root cause (confirmed against current code)
`src/artisanlib/roast_properties.py`, class `editGraphDlg`:

1. **PRIMARY** — `populatePlusCoffeeBlendCombos()`: on a completed roast
   (`timeindex[0] > -1 and timeindex[6] > 0`) the coffee/blend combo index is set with the
   change-signal BLOCKED — by design, so `coffeeSelectionChanged → fillCoffeeData` does not
   re-fill (clobber) the saved roast's stored properties. Side effect: the title auto-refresh
   (`updateTitle`) normally rides that same signal, so it was suppressed too. On an incomplete
   roast the signal fires and the title refreshes → "sometimes yes / sometimes no".

2. **SECONDARY (strand)** — `updateTitle()` / `_setTitleFromReference()` only overwrote a title
   contained in `titles_to_be_overwritten` (empty / «Roaster Scope» / the label of the *current*
   or *immediately previous* coffee/blend). Once a title became stale (showing an *earlier*
   coffee the selection had already moved on from), neither path recognised it as auto-derived, so
   the reference path could not fix it either — while this guard still has to protect a user-typed
   custom title.

3. **Cloud send** — `src/plus/roast.py`: `getRoast()` → `getTemplate()` maps `title` → `label`
   (`roast.py:149`), and `'label'` is in `sync_record_attributes`
   (`sync_record_empty_string_supressed_attributes`, `roast.py:504`). `getSyncRecord()`
   (`roast.py:537`) hashes every `sync_record_attributes` value, so the title participates in the
   sync hash already.

## Key changes (`src/artisanlib/roast_properties.py`)
- **`last_auto_title` tracker** (`roast_properties.py:1343`): remembers the exact string the dialog
  last *auto-applied* to the title (from a coffee/blend selection, a reference, or a recent roast).
  Seeded from the loaded title just before the initial populate
  (`roast_properties.py:1756`) **only** if it equals what the loaded coffee/blend would
  auto-fill — so a genuinely custom loaded title is treated as custom and protected.
- **`_autoTitleCandidate()`** (`roast_properties.py:2273`): single source of truth for "what title
  does the current selection derive" (blend label → coffee lot label → «Roaster Scope»), shared by
  `updateTitle()` and the seeding above so they can never drift apart.
- **`_titleIsAutoDerived(*prev_labels)`** (`roast_properties.py:2283`): the guard. A title is
  overwritable iff it is empty/«Roaster Scope», equals `last_auto_title` (this is what defeats the
  strand — a stale prior title is still recognised), or matches a supplied previous coffee/blend
  label (full or country-stripped lot form). A user-typed custom title matches none → never touched.
- **`_applyAutoTitle()`** (`roast_properties.py:2302`): writes the title and records it in
  `last_auto_title`.
- **`updateTitle()`** (`roast_properties.py:2309`) and **`_setTitleFromReference()`**
  (`roast_properties.py:2674`) reduced to: if `_titleIsAutoDerived(...)`, apply the new title.
- **Decoupled title-only refresh on completed roasts** — in the two completed-roast branches of
  `populatePlusCoffeeBlendCombos()` (coffee `roast_properties.py:2162`, blend
  `roast_properties.py:2212`), after the index is set with the signal still blocked, call
  `self.updateTitle(...)` explicitly. This refreshes the title **without** running
  `fillCoffeeData` (no property fill).
- **Recent-roast path** (`roast_properties.py:2927`): now routes through `_applyAutoTitle()` so the
  tracker stays consistent.

## How the title refresh is decoupled from the property fill
The property protection lives entirely in the *blocked change-signal*: with the signal blocked,
`coffeeSelectionChanged → fillCoffeeData` (which writes beans/density/moisture/screen size) never
runs on a completed roast. The fix does **not** unblock that signal and does **not** call
`fillCoffeeData`. It calls `updateTitle()` directly, which only ever touches the title widget
(`titleedit`) and `last_auto_title`. So the title now follows the selection while the stored
properties remain protected exactly as before.

## Proof the stored properties are NOT clobbered
- Static: the only code added to the completed-roast branches is `self.updateTitle(...)`. Its entire
  call graph is `_titleIsAutoDerived` (reads) + `_applyAutoTitle` (writes `titleedit` +
  `last_auto_title`) + `_autoTitleCandidate` (reads). It contains **no** writes to `beansedit`,
  `bean_density_in_edit`, `moisture_greens_edit`, `bean_size_min_edit`, `bean_size_max_edit`,
  `volumeinedit`, or any `modified_*` field. `fillCoffeeData`/`fillBlendData` are untouched and are
  still gated behind the still-blocked signal.
- `_applyAutoTitle` uses `setEditText`, whose only connected slots are `recentRoastEnabled`
  (button enable/disable) and `RoastsComboBox.textEdited` (updates an internal string). The
  property-filling `recentRoastActivated` is wired to `activated`, which `setEditText` does not emit.
- The property-protection blocked-signal logic (the reason the suppression exists) is unchanged.

## How the corrected title reaches the cloud on OFF
- On dialog OK, `qmc.title` is set from the title widget's current text
  (`roast_properties.py:5977+`), so whatever the (now correctly refreshed) title shows is persisted.
- At OFF/reset the final update calls `plus.controller.updateSyncRecordHashAndSync()` →
  `roast.getSyncRecord(getRoast())`. `getRoast()` emits the title as `label`, `label` is in
  `sync_record_attributes`, and `getSyncRecord()` folds every such value into the SHA-256 hash. A
  title-only change therefore changes the hash and re-syncs. No change needed here — verified.

## Watch-outs
- `_titleIsAutoDerived` relies on `last_auto_title` to defeat the strand. It is correctly seeded at
  open (custom titles → `None` → protected). If a future change adds another code path that sets the
  title, route it through `_applyAutoTitle()` (as the recent-roast path now is) so the tracker stays
  accurate.
- A title the user types that is byte-identical to the auto-derived candidate is (harmlessly)
  treated as auto — same behaviour as the previous label-matching guard.
- `_setTitleFromReference` is now slightly more permissive (also tolerates the blend lot-form and
  the title-label lot-form), a superset of the prior overwritable set — no coverage lost.

## Verification (what was run)
- New regression tests: `src/test/unitary/artisanlib/test_roast_title_refresh.py` (13 tests) —
  cover `_autoTitleCandidate`, auto-refresh on coffee change, empty/«Roaster Scope» refresh,
  custom-title protection, the strand via `last_auto_title`, and coffee→reference in sequence
  (incl. the stale strand and custom protection). All pass.
- Existing title test `test_roast_title_lot_label.py` still passes.
- `python3 -m pytest test/unitary/artisanlib` → **1869 passed, 3 skipped** (master baseline was
  1856 passed; +13 = my new tests; zero regressions).
- Full `test/unitary`: 53 failures, **all pre-existing on master** and all in `src/plus/`
  (test_login/test_register/test_roast/test_sync — environment/mock-ordering, untouched by this
  change). Master baseline: 53 failed / 2264 passed; this branch: 53 failed / 2277 passed.
- `python3 -m py_compile artisanlib/roast_properties.py` → OK. `ruff` introduces no new findings
  (the 3 pre-existing E702 warnings are unrelated lines).
- Note on manual GUI repro: a full end-to-end click-through needs a plus account with stock + a
  completed cloud roast; the title decision logic is verified by the unit tests above (bound to the
  real `editGraphDlg` methods), and the property-protection is guaranteed statically as shown.

## Merge readiness
Ready. Narrow change confined to `editGraphDlg` title handling; property protection unchanged and
proven intact; cloud sync already carries the title and re-syncs on a title-only change. Branch is
committed, not merged, tree clean.
