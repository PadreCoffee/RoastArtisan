# Post-DROP / pre-OFF edits not reaching Roastlocal cloud — Artisan client investigation

_2026-09-06 · Artisan client side · investigated against `master` (prod = 1.0.7) · read-only, then client fix on branch `fix/plus-reupload-profile-after-postdrop-edit`._

## Symptom (prod)

In Artisan, if the roaster changes the DROP / end point (or something else in the profile) **after
DROP but before turning the machine OFF**, the Roastlocal cloud roast does not update, though it should.

## Verified finding (from the client code)

A corrected DROP/curve reaches the cloud **only** through a profile re-upload
(`POST /api/v1/roasts/{id}/upload-profile`); a plain `POST /api/v1/aroast` update carries no
curve/event data. In the shipped client (`master`/1.0.7) the profile is uploaded **exactly once,
on the first DROP**. Any post-DROP edit made **not** through the Roast Properties dialog (dragging /
re-marking the DROP marker, undo + re-press DROP, or editing the curve elsewhere) was **not**
re-uploaded, and OFF / save only sent an `/aroast` diff — so the correction was lost. **This is a
client-side gap.**

## Send sequence (who sends what, with evidence)

Full record → `/aroast` **plus** `upload-profile` (cloud re-derives DROP/first-crack/DRY/TP/DEV +
telemetry) is queued from `addRoast()` with no argument, which builds `roast.getRoast()`; a full
record (`is_full_roast_record`, `date`+`amount`+`roast_id`, `plus/queue.py:557`) attaches the
profile (`plus/queue.py:703`). Call sites:

- **First DROP only** — `artisanlib/canvas.py:4361` and `artisanlib/canvas.py:15428`, both guarded by
  `firstDROP` (`timeindex[6] == 0`). Comment at `artisanlib/canvas.py:15320`: _"on UNDO DROP we do not
  send the record to plus"_.
- **Roast Properties dialog → OK, while recording** — `artisanlib/roast_properties.py:6455`, guarded by
  `flagstart and safesaveflag and timeindex[0] > -1 and timeindex[6] > 0`. (The dialog can edit DROP:
  `dropedit` → `timeindex[6]`, `artisanlib/roast_properties.py:767`.)

Diff → `/aroast` only (weight / name / colours / comment / inventory — **no** curve/event) is queued
from `updateSyncRecordHashAndSync()` → `queue.addRoast(sync_record)` → `diffCachedSyncRecord`
(`plus/controller.py:489,497`). It is called on **manual save** (`artisanlib/main.py:17606`),
**autosave/OFF** (`artisanlib/main.py:13421`), and the **scheduler** (`plus/schedule.py:3247`).

So before this fix, editing the DROP by any means other than the properties dialog produced only an
`/aroast` diff at OFF → the DROP correction never reached the cloud.

## `modified_at` (monotonicity)

The client sets `modified_at` from the **saved file's mtime**, not a monotonic wall-clock:
`getModificationDate(aw.curFile)` (`plus/roast.py:438-440`); only when there is no saved file does
`addRoast` fall back to "now" (`plus/queue.py:672-673`). If an `/aroast` update is sent whose
`modified_at` is not newer than what the cloud already stored, the cloud 409s and applies nothing.
Secondary contributor; worth the cloud team confirming the 409 behaviour against file-mtime timestamps.

## Client fix (done on this branch)

`plus/controller.py` — new `reuploadProfileIfCompleted(roast_record)`, called from
`updateSyncRecordHashAndSync()` inside the `is_synced()` branch. On every **save / OFF / scheduler**
sync of a **synced, completed** roast (CHARGE and DROP set), it re-queues the current profile via
`queue.addProfileUpload(...)`, so a post-DROP correction (marker move, undo+re-DROP, properties edit)
is re-uploaded and the cloud re-derives the DROP from telemetry. Deduplicated by
`(roast_id, path, mtime, size)` in `addProfileUpload`, so an unchanged profile is not re-sent.
Covered by 6 unit tests in `src/test/unitary/plus/test_controller.py`
(`TestReuploadProfileIfCompleted`). No regression (pre-existing keyring-backend failures are identical
on pristine `master`). Not yet built/shipped — pending owner decision.

## Remaining cloud-side gap (hand back to the cloud team)

The client fix makes the corrected profile land, but per the cloud contract the re-upload path treats
**END/COOL, SCs/SCe, charge_temp and weight_loss as fill-only** (not overwritten). Only DROP
(`timeindex[6]`), first-crack, DRY, TP, DEV and raw telemetry are overwritten. Therefore an edit that
changes **specifically** END/COOL/SCs/SCe/charge_temp/weight_loss will still not land, even with the
client re-upload. If those markers should be correctable after the first upload, the cloud must make
them telemetry-authoritative on re-upload.

## Recommendation: both

- **Client (done, this branch):** re-upload the corrected profile on save/OFF of a completed synced
  roast — fixes the DROP/first-crack/DRY/TP/DEV/telemetry case (the reported symptom).
- **Cloud:** (a) make END/COOL/SCs/SCe/charge_temp/weight_loss telemetry-authoritative on re-upload if
  those should be editable post-upload; (b) verify the `modified_at` 409 rule tolerates the client's
  file-mtime timestamps.
