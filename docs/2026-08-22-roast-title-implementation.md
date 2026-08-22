# Roast-title / reference-selection — implementation (C56)

**Type:** implementation. Branch `fix/roast-title-follows-selection`, off `master` @ `2df53190b`
(the merge of `fix/roast-title-follows-reference`, i.e. **TITLE-2 is present**).
**Date:** 2026-08-22.

All line references are to `src/artisanlib/roast_properties.py` unless another file is named.

---

## Step 0 — ground truth on current master (BEFORE writing code)

The owner's four observations predate the TITLE-2 merge (2026-08-07). Current master already
contains TITLE-2, so some of what he saw may already be fixed. I re-tested each observation
**against current master** before changing anything.

**Environment note.** I could not run the full GUI end-to-end — it needs a live Roastlocal Cloud
plus-account, a stock of coffees carrying references, and a completed cloud roast, none of which is
available here. Instead I drove the **real `MyQComboBox` widget through its real
`currentIndexChanged` / `activated` signals** and the real `editGraphDlg` methods in a headless
harness (`QT_QPA_PLATFORM=offscreen`). Each observation is entirely client-side (signal wiring,
combo enable/disable, UUID comparison), so this micro-harness reproduces exactly the behaviour each
observation is about. These verdicts are therefore **VERIFIED at the client-behaviour level** — not
merely code-read — though not through a live cloud round-trip.

| # | Owner's observation | Verdict on current master | Evidence |
|---|---|---|---|
| (a) | Picking a reference **manually** from the эталон dropdown does not change the title | **FIXED** | Real `setCurrentIndex(1)` on the live combo → title becomes the reference name. TITLE-2 wired `currentIndexChanged → templateSelectionChanged → _setTitleFromReference`. |
| (b) | Picking a **coffee** (reference chosen automatically) does not change the title | **STILL BROKEN** | `_applyTemplatesToCombo` leaves the combo at index 0 and the title unchanged: no reference is auto-selected, and the index-set is under `blockSignals`. |
| (c) | With no bean/blend selected, the эталон control is **disabled** | **STILL BROKEN** | `populateTemplateCombo`'s no-coffee branch cleared state, showed only «Без эталона» and **disabled** the combo. |
| (d) | Opening Roast Properties can silently reset the reference to «Без эталона» | **STILL BROKEN (conditional)** | (d2) a roast with a loaded reference but **no** saved `plus_coffee`/`plus_blend`: open set `template_uuid = None` → reference lost. (d3) the seed at line 630 took `backgroundUUID` **raw**; the fetched ids are `normalizeUUID`-normalised → a dashed-vs-bare-hex compare never matches → on a coffee change the reference is dropped, on a pure open it is **duplicated**. |

This matches the investigation's prediction exactly: (a) already fixed by TITLE-2; (b), (c), (d)
still broken. **I did not re-fix (a).** `_setTitleFromReference` stays unconditional per the spec —
a title (typed or otherwise) is replaced when any reference is subsequently selected.

---

## Scope — what I implemented, given that table

Fixed (b), (c) and (d); pinned (a), rule 2 and rule 3 with regression tests. All changes are in
`src/artisanlib/roast_properties.py`; no other runtime file was touched (`plus/stock.py`,
`plus/roast.py`, the cloud — all left as-is; see "What I deliberately did NOT touch").

Mapping to the confirmed spec:

- **Rule 1 (any reference selected → title = its name), automatic path** — the (b) fix. After
  `_applyTemplatesToCombo` sets the index under blocked signals, the title is now updated
  **explicitly** for an auto-selected reference, mirroring exactly how TITLE-1 already calls
  `updateTitle` explicitly in the blocked completed-roast branch (`2175`/`2224`). `blockSignals`
  is **not** removed.
- **Rule 1, coffee/blend selection** — when the operator picks a coffee/blend and references
  arrive, the coffee/blend's reference is now auto-selected (the **first** item, as the cloud
  orders them: lot-matched, then newest) instead of leaving index 0. If **zero** references come
  back, «Без эталона» stays (rule 3).
- **Rule 2 / rule 3 (bean with no reference → title unchanged / no эталон)** — no behaviour change;
  pinned with tests. The auto-retitle fires **only** when a reference is actually auto-selected, so
  a coffee with no references never fabricates one.
- **Rule 4 (open overwrites nothing)** — the no-coffee hard-clear is gone (so a loaded reference
  survives an open even with beans-as-free-text), and the seed is normalised so the compare can't
  fail on UUID format alone.
- **Rule 5 (no bean/blend → reference still pickable)** — `populateTemplateCombo` no longer
  disables the control when nothing is selected; it fetches references with the **machine only**
  and keeps the control enabled.

---

## Key changes (file: `src/artisanlib/roast_properties.py`)

1. **Seed normalisation (rule 4, line ~630).**
   `self.template_uuid = plus.util.normalizeUUID(self.aw.qmc.backgroundUUID)` replaces the raw
   `backgroundUUID if backgroundUUID else None`. `normalizeUUID(None)`/`('')` both return `None`,
   so the old guard is subsumed; the value now matches the normalised fetch ids used at
   `2639`/`2656`. `org_template_uuid` (the accept()/Cancel snapshot) is taken from it, so both
   sides of every later comparison are normalised consistently. Idempotent on already-normalised
   ids (the common case, since `main.py:14615` already normalises on load), so nothing changes for
   normally-stored roasts.

2. **One-shot auto-select flag (rule 1, line ~1351).** New instance attribute
   `self._select_reference_after_fetch: bool = False`. Set to `True` when the user picks a real
   coffee (`coffeeSelectionChanged`) or blend (`blendSelectionChanged`), reset to `False` on a
   deselection, and **consumed** by the next `_applyTemplatesToCombo`. It is never set on a pure
   open, so opening the dialog cannot trigger an auto-select (rule 4).

3. **`_applyTemplatesToCombo` (rule 1, ~2667).** After computing `selected_idx` from a matching
   `template_uuid`, when the one-shot flag is set and no reference resolved (`selected_idx == 0`)
   and references exist, it auto-selects the first (`selected_idx = 1`), records
   `template_uuid`/`template_file`/`template_is_reference`, and — **after unblocking** — calls
   `_setTitleFromReference(label)` **explicitly**. The flag is consumed unconditionally so a later
   background refetch does not re-drive a selection the user may have since changed by hand.

4. **`populateTemplateCombo` (rules 5 + 4, ~2589).** The `if not (coffee_hr_id or blend_hr_id): …
   disable … return` block is removed. Control now always falls through to the fetch: the remote
   path calls `getReferencesFromAPI(coffee_hr_id, blend_hr_id, machine)` with both ids possibly
   `None` (→ machine-only fetch, which the backend answers with the unbound + this-machine set),
   and `_applyTemplatesToCombo` preserves/injects any loaded reference and enables the combo when
   there are items.

Test file added: `src/test/unitary/artisanlib/test_roast_title_follows_selection.py` (12 tests,
all through the real Qt signal path / real `_applyTemplatesToCombo` / real `populateTemplateCombo`).

---

## Important findings (things the diff does not show)

- **`getReferencesFromAPI` already had the machine-only fallback the client never reached.**
  `plus/stock.py:1822-1835` already retries **without** the coffee/blend filter (machine only)
  when a filtered fetch returns zero. But rule 5's bug was *upstream*: `populateTemplateCombo`
  early-returned and disabled the combo **before** any fetch when no coffee/blend was selected, so
  that fallback was never exercised in the no-bean case. My change routes the no-bean case through
  the same fetch, so the machine-only request (and thus the cloud's correct rule-5 set) is finally
  issued. **No `plus/stock.py` change was needed.**

- **Where the spec and the TITLE-1/TITLE-2 trade-offs meet — and don't collide.** The automatic
  retitle deliberately reuses TITLE-1's own pattern ("index set under blocked signals, then call
  the title update explicitly"). It does **not** touch TITLE-2's unconditional
  `_setTitleFromReference`, so a manually-typed title is still replaced by any later reference pick
  (owner-confirmed rule 1). The one point where an automatic action now *also* replaces a typed
  title is the coffee-with-a-reference case: pick a coffee that has a reference and its name
  overwrites whatever was typed. That is the direct consequence of "it does not matter whether the
  operator picked it or the system did" (rule 1) and is intended — but it is the sharpest visible
  behaviour change, so it is called out under Watch-outs.

- **Rule 2 needed no code change, but for a subtle reason worth stating.** "A bean with no
  reference → the title does not change" is satisfied because the auto-retitle only fires when a
  reference is actually auto-selected. The *coffee-lot-label* auto-fill on a coffee pick is
  unchanged TITLE-1 behaviour (and is what the 22 existing tests assert); rule 2 forbids
  *fabricating a reference name*, not following the coffee's own lot label. Both are pinned.

- **The one-shot flag, not `user_updated_coffee_or_blend`, drives the auto-select.**
  `user_updated_coffee_or_blend` stays `True` for the rest of the dialog session (even after the
  user manually clears the reference), so reusing it would re-select the reference on every later
  stock-update refetch and stomp the user's «Без эталона». The dedicated one-shot flag is consumed
  once and is the reason `test_rule1_auto_select_is_one_shot_not_repeated_on_refetch` passes.

---

## Watch-outs

- **The owner will now see the title change when he picks a coffee that has a reference** (it
  becomes the reference's name), and when he picks a coffee that has **no** reference the title
  follows that coffee's lot label as before. Both are intended; only the first is new.
- **A hand-typed title is replaced when a coffee that carries a reference is selected** (rule 1,
  automatic). This is the most noticeable change and follows directly from the owner's rule 1. A
  title typed *after* a reference is chosen still survives every coffee/blend refresh; only picking
  another reference (or a reference-bearing coffee) replaces it.
- **No-bean + no machine configured.** When neither a coffee/blend nor a machine name is set,
  `getReferencesFromAPI(None, None, None)` sends no filter at all and the backend returns the
  account's whole reference set. This is the pre-existing `machine or None` behaviour, now also
  reachable in the no-bean case. Flagged as an open question rather than fixed.
- **Scheduler-fallback (remote fetch disabled) + no bean.** `_getTemplatesFromSchedule` matches by
  coffee/blend, so with no bean it returns `[]` and the combo is empty+disabled. That is correct —
  there is no machine-scoped reference source offline — but it means rule 5's "pickable with no
  bean" only holds when remote profile fetch is enabled (the normal cloud case).
- **Deliberately NOT done:** batch weight (out of scope — no reference→weight mechanism exists and
  the owner did not restate it), the `plus/roast.py` upload mapping (carries `qmc.title` faithfully
  — nothing to fix), the `_parseReferenceItems` nested-name fallback (fragility, not the reported
  bug), and any refactor/cleanup.

---

## Verification

### Directly relevant, deterministic suites

```
$ python3 -m pytest test/unitary/artisanlib/test_roast_title_follows_selection.py \
                    test/unitary/artisanlib/test_roast_title_refresh.py -q
..................................                                        [100%]
34 passed in 1.84s
```

(12 new real-signal tests + the 22 pre-existing TITLE-1/TITLE-2 tests — all 22 kept green,
none altered.)

### Negative controls (each new test proven able to fail)

**A — the five fix-tests fail without the fix.** `git stash` the source edit (the new test file is
untracked, so it stays), then run the new suite:

```
$ git stash push -- src/artisanlib/roast_properties.py
$ python3 -m pytest test/unitary/artisanlib/test_roast_title_follows_selection.py -q
5 failed, 7 passed
FAILED …::test_rule1_auto_select_first_reference_and_retitle        (assert 0 == 1)
FAILED …::test_rule1_auto_select_takes_first_of_several             (assert 0 == 1)
FAILED …::test_rule1_auto_select_is_one_shot_not_repeated_on_refetch(assert True is False)
FAILED …::test_rule4_no_coffee_open_preserves_the_loaded_reference  (assert None == 'aaaa…')
FAILED …::test_rule5_no_coffee_keeps_reference_control_enabled…     (assert False is True)
$ git stash pop            # fix restored → 12 passed
```

What went red maps cleanly: the three `rule1_auto_*` tests ← the `_applyTemplatesToCombo`
auto-select + explicit retitle (edits 2/3/6); `rule4_no_coffee_open_preserves…` ← the
`populateTemplateCombo` no-hard-clear (edit 4); `rule5_no_coffee_keeps…enabled` ← the same
no-disable change (edit 4).

**B — the two "pinning" tests are real guards, not tautologies** (they pass on pristine because
they pin already-correct behaviour, so I broke that behaviour to show they can fail):

- `test_rule1_manual_pick_via_real_signal_retitles`: rebuilt with the combo's signals **not
  connected** → `setCurrentIndex(1)` leaves the title at `'El Paraiso'` (RED). Proves the test
  genuinely depends on the live `currentIndexChanged` wiring, not a direct method call.
- `test_rule4_uuid_format_mismatch_does_not_duplicate_or_drop`: fed a **raw dashed** seed
  (simulating the un-normalised pre-fix seed) into `_applyTemplatesToCombo` → the combo shows a
  **duplicate** `Reference Roast #7` entry (RED). Proves the seed normalisation is what prevents
  the duplicate/drop.

### Full suite — no regressions anywhere

Full suite is deterministic at **53 failed, 2415 passed, 3 skipped** across three consecutive runs
on the fixed code. The 53 failures are pre-existing and unrelated (`plus/test_login`,
`plus/test_register`, `plus/test_roast`, `plus/test_sync`, plus a few flaky Qt-dialog tests that
leak global state) — none touch `roast_properties.py`.

Diffing the failing **test ids** between pristine `master` and the fixed branch (same command,
same ordering) is airtight:

```
REGRESSIONS  (fail on FIXED, not on pristine):   <none>
FIXED BY CHANGE (fail on pristine, not on fixed):
  test_roast_title_follows_selection.py::test_rule1_auto_select_first_reference_and_retitle
  test_roast_title_follows_selection.py::test_rule1_auto_select_is_one_shot_not_repeated_on_refetch
  test_roast_title_follows_selection.py::test_rule1_auto_select_takes_first_of_several
  test_roast_title_follows_selection.py::test_rule4_no_coffee_open_preserves_the_loaded_reference
  test_roast_title_follows_selection.py::test_rule5_no_coffee_keeps_reference_control_enabled_with_references
```

Pristine = 58 failed, fixed = 53 failed; the difference is **exactly** the 5 fix-tests and nothing
else. My change introduces zero new failures.

---

## Open questions for the owner

1. **No-bean + no machine configured** → the client would request the account's *entire* reference
   set (no filter). Acceptable, or should the no-bean fetch be suppressed when the machine name is
   empty?
2. **Coffee with several references.** The spec says "take the first as the cloud orders them". I
   auto-select `templates[0]`. Confirm the cloud's list order (lot-matched first, then newest) is
   what you want the title to default to when a coffee carries more than one reference.
3. **Rule 1 aggressiveness.** Selecting a coffee that carries a reference now overwrites a
   hand-typed title with the reference name. Confirmed as intended by rule 1 — flagging once more
   because it is the most visible change.
4. **Batch weight** remains untouched (out of scope). Still a separate decision if you want it to
   follow the reference.
