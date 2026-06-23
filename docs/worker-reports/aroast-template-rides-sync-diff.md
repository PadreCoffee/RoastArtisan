# ARTISAN-REF-STAMP — reference link lost on cloud-reference roasts

**Branch:** `fix/aroast-template-rides-sync-diff`
**Commit:** `ff71c0d7c`
**Scope:** one narrow, additive client fix in `src/plus/roast.py` + regression tests.

## Cloud contract (unchanged — matched from the client)

The cloud links a roast to a reference profile **only** when the `/aroast` payload's
`template` object carries **both** the reference `id` **and** `is_reference: true`:

```json
"template": { "id": "<reference-roast-uuid>", "is_reference": true }
```

A flag-less `template: { "id": ... }` is a **manual** background (loaded `.alog` or a past
roast) and is deliberately **not** linked. There is no other channel — the cloud does not read
a bare `reference_profile_id`. The fix does not touch the cloud.

## What the client already got right (reference-vs-manual distinction)

The client-side distinction was already implemented (prior commits `63483104f`, `02f436d85`,
`b7dcb15ca`) and is correct:

- The **cloud-reference selector** is the эталон combo in the Roast Properties dialog. Choosing
  an entry sets `template_is_reference = (template_uuid is not None)`
  (`roast_properties.py:2626`); «Без эталона» clears it.
- On apply, that becomes `aw.qmc.backgroundIsReference` (`roast_properties.py:6197/6219`).
  `loadbackground()` force-clears the flag on every load, so a manual `.alog` load or a
  past-roast background never carries it.
- The flag persists across autosave/restart via `getProfile`/`setProfile`
  (`backgroundIsReference` key) — covered by `test_background_reference.py`.
- `getRoast()` stamps the template:
  ```python
  if aw.qmc.backgroundUUID:
      d['template'] = {'id': aw.qmc.backgroundUUID}
      if getattr(aw.qmc, 'backgroundIsReference', False):
          d['template']['is_reference'] = True
  ```
  This is correct for the **full DROP upload**.

## Root cause (the remaining gap — the diff/update path)

There are two upload paths in `plus/queue.py::addRoast`:

| Path | Source record | Carries `template`? |
|------|---------------|---------------------|
| DROP / new roast (`roast_record is None`) | `roast.getRoast()` (full) | **yes** ✓ |
| Update / re-sync (`roast_record` passed) | `roast.getSyncRecord(...)` (diff) | **no** ✗ |

`getSyncRecord()` rebuilds the payload by copying only `sync_record_attributes`
(`roast.py:545`). `template` is a **nested dict**, not a bidirectionally-synced scalar, and is
in **none** of the four `sync_record_*` lists — so it was silently stripped from every diff
update.

The update path is driven by `controller.updateSyncRecordHashAndSync()` (called from
`filesave()`, `automaticsave()`, scheduler), which does
`queue.addRoast(getSyncRecord(getRoast())[0])`.

**Why this loses the link in practice:** the эталон combo lives in the **Roast Properties
dialog**, which operators open **after** the roast. So a cloud reference is normally
selected/changed **after DROP** — exclusively through the diff path. The full DROP record (which
would have carried the flag) was already sent before the reference existed, and the later
property-save that actually adds the reference goes through `getSyncRecord()`, which dropped
`template` entirely. The cloud therefore never received `template.is_reference` and never linked
the roast.

A secondary effect: since `template` was absent from the sync hash, toggling the reference did
not even register as a sync change, so in some cases no update fired at all.

## The fix

`src/plus/roast.py`, in `getSyncRecord()` — after copying `sync_record_attributes`, carry the
`template` object through unchanged and fold it into the change-detection hash:

```python
if 'template' in r:
    d['template'] = r['template']
    m.update(str(r['template']).encode('utf-8'))
```

This is minimal and additive:

- **Cloud reference** → diff update now carries `{id, is_reference: true}` → cloud links.
- **Manual / past-roast background** → diff update carries `{id}` only (no flag) → cloud still
  does **not** auto-link (contract preserved).
- **No background** → no `template` (unchanged).
- The `template` is now part of the sync hash, so selecting/changing a reference after DROP
  registers as a sync update and the diff upload actually fires.

Downstream is safe: `diffCachedSyncRecord()` keeps `template` when it differs from the cached
record (and drops it when identical, avoiding needless re-sends); `suppress_zero_values()` and
`applyServerUpdates()` only touch explicit scalar keys, so neither mangles the nested dict.
`template` is intentionally **not** added to `sync_record_attributes` — it stays out of the
zero-suppression / bidirectional-overwrite machinery and is purely client→cloud.

## Verification

`getSyncRecord` cannot be imported fully headless (it pulls Qt via `plus.stock`), so it was
exercised with the project's existing module-mock approach (giving real types where annotations
evaluate at def time):

```
ref  : {'id': 'u', 'is_reference': True}   # cloud reference rides the diff
man  : {'id': 'u'}                          # manual background: id only, no flag
none : None                                 # no background: no template
hash differs on ref toggle: True            # selecting a reference triggers an update
```

Added `TestGetSyncRecordTemplateLink` (4 cases) in
`src/test/unitary/plus/test_roast.py` pinning exactly these four contracts.

**Pre-existing, unrelated:** `test/unitary/plus/test_roast.py` and `test_sync.py` currently have
collection/mocking failures under the local Python 3.13 venv (`stock.Blend|None` evaluated
against a `Mock`; a `normalizeUUID` mock assertion) that exist on the clean tree before this
change. The new logic was therefore verified via the isolated harness above; the new tests
follow the file's established style and assert only `getSyncRecord` behavior.

A live cloud round-trip (pick эталон in Roast Properties after DROP → confirm the roast links on
the cloud) should be run by the owner against a real account; the payload-level evidence above
shows the outgoing `/aroast` diff now carries `template.is_reference: true`.

## Not merged

Committed on `fix/aroast-template-rides-sync-diff` only. Not merged to the client's main per
instructions — awaiting owner approval.
