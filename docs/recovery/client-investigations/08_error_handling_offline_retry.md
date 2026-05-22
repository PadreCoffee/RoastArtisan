# Client Investigation: Error handling, offline mode, timeout, retry, and partial failure behavior

## 1. Research question

How does the modified Artisan client handle cloud errors, offline mode, timeouts, retries, and partial failure, specifically for:
- network exceptions
- HTTP non-2xx handling
- JSON parse failures
- auth failures
- cloud unavailable behavior
- retries
- timeouts
- user-visible error messages
- whether local roast work can continue if cloud is unavailable
- whether failed uploads can be retried later

## 2. Executive summary

The client implements an outbox-style asynchronous upload queue (`plus.queue`) that decouples roast work from immediate cloud availability. Local roasting can continue while disconnected; upload tasks are persisted and retried later.

Network and HTTP failures are mostly handled in queue worker logic with bounded retries (`queue_retries + 1`, default 3 total attempts), delayed retry intervals, and selective disconnect/reconnect behavior. Authentication failures (401) trigger token refresh/re-auth inside `plus.connection`; if still failing, queue-level handling may disconnect while keeping credentials for auto-reconnect.

Timeout behavior includes adaptive read-timeout escalation: request read timeout resets to max on timeout and gradually decreases again on success. However, error handling is heterogeneous: some paths return `None` on timeout (`getData`), others raise exceptions (`sendData`, `sendFile`), and JSON decoding errors are sometimes surfaced as `ValueError` and sometimes only logged.

Partial failure handling is explicit for full roast summary vs full profile upload: summary can succeed while profile upload fails, with dedicated user message and separate queued profile-upload item. Failed uploads can be retried via persisted queue, subject to discard/attempt limits and specific conditions.

## 3. Files inspected

- `src/plus/connection.py`
- `src/plus/queue.py`
- `src/plus/controller.py`
- `src/plus/config.py`
- `src/plus/sync.py`
- `src/test/unitary/plus/test_config.py`
- `src/test/unitary/plus/test_controller.py`
- `src/test/unitary/plus/test_sync.py`
- `src/test/unitary/plus/test_notifications.py`
- `src/test/unitary/plus/test_stock.py`

## 4. Facts from code

1. Queue-based decoupling and persistence
- Outgoing cloud updates are persisted in `persistqueue.SQLiteQueue` at `config.outbox_cache` (`plus.queue.start`, `queue_path`).
- Queue worker runs continuously in its own thread (`Worker.task`) and processes roast uploads asynchronously.
- If disconnected/cloud unavailable, items remain queued until success or discard condition.

2. Retry policy and delays
- Queue retries per item: `iters = config.queue_retries + 1` when `modified_at` exists; default is `2 + 1 = 3` total attempts (`plus.config`, `plus.queue.Worker.task`).
- Delay between failed attempts:
  - `RequestsConnectionError`: `time.sleep(config.queue_retry_delay)` (default 30s).
  - HTTP 401 and generic failures: retries with `queue_retry_delay` or `2 * queue_retry_delay` depending on branch.
- Expiration/drop policy: queued items older than `config.queue_discard_after` (default 3 days) are removed.

3. Timeout handling
- Request timeout tuple is `(connect_timeout, read_timeout)` with defaults `(6s, dynamic read timeout)`.
- Dynamic read-timeout logic:
  - On timeout: `request_read_timeout = read_timeout_max` (default 30s).
  - On success: read timeout decreases stepwise down to baseline `read_timeout` (default 12s).
- Behavior differs by API method:
  - `sendData`/`sendFile`: timeout raises exception.
  - `getData`: timeout returns `None`.

4. Authentication failure handling
- `sendData`, `sendFile`, `getData` detect HTTP 401 and attempt re-authentication (`authentify()`), then retry once with refreshed token.
- `authentify()` clears credentials and returns `False` on multiple failure paths (missing password, failed auth response, certain subscription checks).
- Queue worker on 401 may disconnect connection state (`controller.disconnect(remove_credentials=False, stop_queue=False)`), preserving credentials for reconnect behavior.

5. HTTP non-2xx handling
- Queue worker enforces `r.raise_for_status()` for upload flows; non-2xx becomes exception branch.
- Explicit special-case handling:
  - 401: disconnect logic + retry decrement.
  - 409: stop retry (`iters = 0`) for that item.
- Other HTTP failures consume retry budget and wait before retry.

6. JSON parse failure handling
- `connection.authentify()` uses `r.json()` and catches `JSONDecodeError`, re-raising as `ValueError` with details (or `Empty response`).
- Queue helper `get_response_json()` handles invalid JSON by logging and returning `None` (non-fatal for success path metadata extraction).
- Empty/invalid JSON in reply parsing does not necessarily fail whole worker flow if status is already successful.

7. User-visible error/status messages
- Success and queueing messages include:
  - "Queuing roast for upload to ..."
  - "Roast successfully uploaded to ..."
  - "Full roast profile uploaded to ..."
- Partial-failure messages include:
  - "Roast summary uploaded, but full profile upload failed"
  - "Roast summary uploaded, but full profile upload file is unavailable"
- Connection/auth messages include:
  - "Connected to artisan.plus"
  - "Authentication failed"
  - "Couldn't connect to artisan.plus"
  - "artisan.plus connection lost. Reconnecting automatically..."
  - "artisan.plus reconnected"

8. Offline/cloud unavailable continuity
- Client explicitly distinguishes ON state from connected state (`controller.is_on` vs `is_connected`).
- On connect failures with existing account, queue is still started to allow enqueueing while offline (`controller.connect` exception branch).
- Local roast operations can continue; unsynced roasts are queued and represented by sync/cache mechanisms.

9. Retry of failed uploads later
- Yes, via persisted queue and worker retries; items survive restarts because queue is SQLite-backed.
- Additional logic supports sequencing full roast then profile upload (`addProfileUpload`, `full_roast_in_queue`, sync key checks).
- Failed profile upload after successful summary can be retried as separate queued item (if conditions permit), otherwise user is informed.

## 5. Network/API behavior

| Scenario | Code path | Observed behavior |
|---|---|---|
| Connect timeout / read timeout in `sendData`/`sendFile` | `plus.connection.sendData/sendFile` | Timeout exception raised; read-timeout increased to max; queue worker catches and retries according to policy |
| Timeout in `getData` | `plus.connection.getData` | Returns `None` instead of exception; caller must handle nullable response |
| HTTP 401 during authorized request | `plus.connection.*` | Re-authenticate and retry once with refreshed token |
| HTTP non-2xx in queue upload | `plus.queue.Worker.task` + `raise_for_status()` | Exception path; retry/disconnect logic based on status |
| HTTP 409 in queue upload | `plus.queue.Worker.task` | Retry loop terminated for that item (`iters=0`) |
| JSON invalid in auth response | `plus.connection.authentify` | Raises `ValueError` (after JSON decode handling) |
| JSON invalid in worker metadata extraction | `plus.queue.get_response_json` | Logs decode error; returns `None`; upload success status can still stand |

## 6. Data model mapping

- Outbox item model (`plus.queue`):
  - Common fields: `url`, `data`, `verb`
  - Profile upload item: `type=profile_upload`, `data.roast_id`, `data.profile_path`, `data.modified_at`, `cleanup_profile_path`
- Sync tracking model (`plus.sync`):
  - `sync_cache` maps normalized `roast_id` -> `modified_at` epoch float
  - Used to decide synced state, update eligibility, and profile upload sequencing
- Retry-discard model:
  - Uses `data.modified_at` for age-based discard (`queue_discard_after`)

## 7. Roastlocal Cloud assumptions

Facts inferred from client behavior:
- Cloud accepts roast summary via `POST/PUT` JSON (`/aroast`) and may return authoritative roast ID in multiple response shapes (`roast_id`, `id`, nested `result` variants).
- Cloud exposes separate endpoint for profile upload (`/roasts/{roast_id}/upload-profile`), enabling two-step summary+profile pipeline.
- 401 indicates expired/invalid session token and is expected recoverable via re-auth.
- 409 is treated as non-retryable conflict for queue item.

Inference (explicit):
- The client assumes temporary cloud/network failures are common enough to require durable outbox and delayed retries.

## 8. Artisan compatibility assumptions

- Sync compatibility depends on preserving `roast_id`/UUID normalization and `modified_at` semantics across queue/sync cache.
- Partial update logic (`sync.diffCachedSyncRecord`) assumes server supports partial roast updates.
- Keeping queue active even when not connected is an intentional compatibility behavior to avoid blocking roast workflow.

## 9. Conflicts and contradictions

1. Inconsistent timeout error contract
- `getData` returns `None` on timeout, while `sendData/sendFile` raise timeout exceptions.
- This asymmetry increases caller-side branching complexity and can hide timeout causes if caller does not log `None` origin.

2. Auth retry log message inconsistency
- In `getData`, 401 branch log says "session token outdated (404)" though condition checks 401.
- Functional behavior is 401 handling; log text is contradictory/noisy for diagnostics.

3. Error handling granularity varies
- Some paths surface detailed decode exceptions; others only log and continue.
- This may produce different observability for equivalent JSON issues.

## 10. Risks

- Items can be dropped after `queue_discard_after` (default 3 days), creating eventual data loss risk if prolonged outage persists.
- Retry count is bounded (default 3 attempts per processing cycle for eligible items); persistent hard failures require later re-processing opportunities or manual intervention.
- Broad `except Exception` in many locations can suppress actionable error typing and complicate incident triage.
- Queue/profile sequencing depends on sync key presence; if sync cache state is corrupted/missing, profile upload may be skipped or requeued conditionally.

## 11. What must not be broken

- Durable outbox queue persistence (`persistqueue.SQLiteQueue`) and restart continuity.
- 401 re-auth-and-retry flow in `connection` methods.
- Separation of roast summary upload and profile upload with partial-failure messaging.
- Ability to queue roasts while not connected (offline continuity).
- Sync cache updates (`sync.addSync`) after successful upload to prevent duplicate/invalid sync state.

## 12. Owner questions

1. Is `queue_discard_after=3 days` acceptable for production outages, or should this be longer/disabled for critical environments?
2. Should HTTP 409 remain non-retryable always, or do some Roastlocal conflict cases require retry/backoff with merge semantics?
3. Do we require uniform timeout behavior (`raise` vs `None`) across `getData` and write methods for better observability and error handling?
4. For prolonged offline periods, is user-facing visibility of pending queue depth/status sufficient, or should explicit UI backlog indicators be added?
5. For failed profile uploads after summary success, should we provide explicit manual retry controls in UI beyond automatic queue handling?

## 13. Suggested next investigation

Focused investigation 09: "Outbox durability and recovery edge cases"
- Validate queue behavior across app restarts/crashes/power loss.
- Validate lock/file corruption recovery paths for `sync` cache and queue DB.
- Map exact conditions that lead to item discard, duplicate submission, or profile-upload orphan states.
- Capture a scenario matrix (network down, 401 loops, 409 conflict, malformed JSON, profile file missing) with expected vs observed queue outcomes.
