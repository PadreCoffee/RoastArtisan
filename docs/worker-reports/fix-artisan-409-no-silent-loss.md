# Worker report: fix Artisan 409 silent roast-save loss

Branch: `fix/artisan-409-no-silent-loss` (off `master`)

## Scope

On an HTTP 409 (and other non-2xx) response to `POST /api/v1/aroast`, the
upload worker silently discarded the roast: it set `iters = 0`, called
`queue.task_done()` (which removes the item), never read/logged the 409 body,
and showed the roaster no notification. A rejected save was lost without trace.

This change makes a rejected roast **save** loud: log the response body with the
roast id, and show the roaster a visible notification. Scope is limited to the
`/aroast` save path. The success path (200/201/204), the profile-upload-after-
success flow, the lock-schedule path, and the 401 re-auth path are unchanged.

## Key changes per file

`src/plus/queue.py` (only file touched):

1. **New helper `extract_response_reason(r)`** — returns a short, human-readable
   reason from a non-2xx response. Prefers a structured field (`error`,
   `message`, `detail`, `reason`) at the top level or under `result`, then falls
   back to trimmed raw `r.text` (≤300 chars). Reuses the existing
   `get_response_json()` content-type/JSON guards.

2. **New helper `report_save_rejected(r, roast_id, *, conflict)`** — logs the
   full response body at ERROR level with status + roast id (so the reason is
   recoverable from client logs even when there is no structured field), then
   calls `aw.sendmessage(...)` with a translated, user-facing message including
   the short reason when available. Mirrors the existing
   worker-thread-to-`sendmessage` pattern already used in this file (e.g. the
   profile-upload-failure message).

3. **New `save_item` flag** in `Worker.task()`, alongside the existing
   `profile_item`: `True` when the item is a non-profile POST to
   `config.roast_url` (i.e. `/aroast`). Used to gate the new reporting so only
   the save path is affected.

4. **409 branch**: still `iters = 0` (stop retrying — a genuine conflict will
   never succeed on blind retry), but now also calls `report_save_rejected(...,
   conflict=True)` for save items.

5. **Generic non-2xx `else` branch**: unchanged finite-retry behaviour
   (`config.queue_retries` then drop), but when retries are exhausted
   (`iters == 0`) for a save item it now calls `report_save_rejected(...,
   conflict=False)` instead of dropping silently.

## Important findings — the queue / retry / notify decision (and why)

- **Retry policy chosen: notify + drop, never silent. No new infinite retry.**
  - **409 (conflict):** stop retrying immediately (`iters = 0`, the pre-existing
    behaviour). A conflict such as "server has a newer version" or a server-side
    business rejection (the confirmed case: insufficient-stock) will never
    succeed on a blind retry, so retrying would spin forever. We keep the
    single attempt but make the failure loud (log body + notify).
  - **Other non-2xx (e.g. 400/422/500):** keep the existing finite retry
    (`config.queue_retries` = 2), then on final exhaustion log + notify instead
    of dropping silently.
- **Why drop rather than keep for manual retry:** the worker always calls
  `queue.task_done()` at the end of the loop, so items are always removed once
  processed; there is no surfaced manual-retry UI. The established pattern in
  this file for an unrecoverable upload failure (see the profile-upload-failure
  branch) is exactly "notify + drop". Re-queueing a 409 item would recreate the
  infinite loop the task warns against. So we deliberately notify + drop with a
  logged reason rather than re-enqueue.
- **Why gate on `save_item` (url == `config.roast_url`):** the worker's
  exception handler is shared by profile uploads, lock-schedule posts, and roast
  saves. Profile items already have their own failure notification
  (`'Roast summary uploaded, but full profile upload failed'`), so gating on
  `save_item` prevents double-notifying profile items and leaves the
  lock-schedule path untouched.
- **401 left as-is:** by the time a 401 reaches the worker, `sendData()` has
  already attempted a re-authentify, and `authentify()`/`clearCredentials()`
  surface their own error to the user. Per task scope we did not refactor it.

## Watch-outs for master

- **Worker-thread `sendmessage`:** `report_save_rejected` calls
  `aw.sendmessage()` directly from the queue worker thread. This matches the
  existing code in the same handler (the profile-failure message and the
  success messages all call `sendmessage` from this thread), so it is not a new
  risk — but if `sendmessage` is ever made strictly GUI-thread-only, all of
  these call sites (not just the new one) must move to a signal.
- **`save_item` classification by URL:** relies on items being enqueued with
  `item['url'] == config.roast_url` (as `queue_roast_item` does). If a future
  change enqueues saves under a different/derived URL, update this check.
- **No behaviour change on success or for profile/lock-schedule items** — the
  new code only runs inside the failure branches and only for save items.

## Flags

- None blocking. The user-facing strings are new translation sources
  (`'Roast save was rejected by {} (conflict) and was not uploaded'` and
  `'Roast save failed and was not uploaded to {}'`) under the `Plus` context;
  they will show in English until translations are regenerated.

## Verification — what ran + manual steps

Ran (in the worktree, `src/`):

- `python3 -c "import py_compile; py_compile.compile('plus/queue.py', doraise=True)"`
  → **queue.py OK** (compiles clean).
- `git diff --check` → clean (no whitespace errors).
- `python3 -m pytest test/unitary/plus/ -q`
  → **93 failed, 326 passed, 19 errors**, identical to the same run with this
  change stashed (verified via `git stash` / `pop`). The failures are
  pre-existing (concentrated in `test_stock.py` / `test_sync.py`) and unrelated
  to this change. There is **no** `test_queue.py` covering the worker loop, so
  no unit test exercises the patched code directly.

Manual test the owner should do:

1. Point the client at a backend (or a stub/proxy) that returns **409** for
   `POST /api/v1/aroast` (e.g. reproduce the insufficient-stock case, or stub the
   endpoint).
2. Complete/save a roast so it is queued for upload.
3. Confirm **both**:
   - a client log line at ERROR level:
     `roast save rejected (status 409) for roast_id=<id>: <body>` — the full
     response body is present;
   - a visible in-app message: `Roast save was rejected by RoastArtisan
     (conflict) and was not uploaded (<reason>)`.
4. Confirm the item is removed from the queue (no infinite retry / no spinning)
   and that a subsequent successful save still works normally.
5. (Optional) Repeat with a 500 to confirm the finite-retry path also ends with
   a logged body + `Roast save failed and was not uploaded to RoastArtisan`
   notification after retries are exhausted.

## Merge readiness

Ready for owner review. Single-file, surgical change; compiles; no new test
regressions; success/profile/lock-schedule/401 paths untouched. **Not merged** —
awaiting explicit owner go-ahead. Full PyQt runtime verification (the manual
steps above) could not be performed headless and should be done by the owner
before release.
