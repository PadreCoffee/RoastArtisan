# Client Investigation: HTTP/network communication with Roastlocal Cloud

## 1. Research question

How does the modified Artisan client perform HTTP/network communication with Roastlocal Cloud, including transport library, request construction, headers, authentication/session handling, timeouts, retries, error handling, JSON handling, file upload/download, sync model, logging, and base URL configuration?

## 2. Executive summary

The modified client uses the Python `requests` library as a synchronous HTTP transport wrapper concentrated in `src/plus/connection.py`, with higher-level call sites in `plus.stock`, `plus.queue`, `plus.sync`, `plus.notifications`, and `plus.schedule`.

Communication is token-based (`Authorization: Bearer ...`) and includes one automatic re-authentication cycle on `401` inside transport methods. Requests are synchronous and run mostly inside worker threads (`QThread`) to avoid direct GUI blocking, with semaphores used to prevent stacked parallel fetches.

Request payloads are JSON-encoded manually (`json.dumps(...).encode('utf8')`), optionally gzip-compressed for larger POST/PUT bodies, and include an idempotency key on POST. A separate multipart upload path exists for full roast profile files (`/roasts/{roast_id}/upload-profile`).

Base URL configuration is centralized in `plus.config.set_server_base_url()`: one configured server URL determines both web and API base paths (with auto-derivation of `/api/v1` if not explicitly present). The implementation contains explicit compatibility branching that enables profile upload/fetch only for non-default server URLs.

## 3. Files inspected

- `src/plus/config.py`
- `src/plus/connection.py`
- `src/plus/controller.py`
- `src/plus/queue.py`
- `src/plus/stock.py`
- `src/plus/notifications.py`
- `src/plus/sync.py`
- `src/plus/schedule.py`
- `src/plus/login.py`

## 4. Facts from code

### 4.1 HTTP client library and call model

Facts:
- HTTP transport uses `requests` (`import requests`, `requests.get/post/put`) in `src/plus/connection.py`.
- Core wrappers:
  - `sendData(url, data, verb, authorized=True, compress=True)` for JSON POST/PUT.
  - `sendFile(url, file_path, field_name='file', authorized=True)` for multipart file upload.
  - `getData(url, authorized=True, params=None)` for GET.
- No async HTTP framework is used (`aiohttp`, Qt network APIs, etc. are not used in this path).

Inference:
- Network operations are synchronous per call. Concurrency is achieved by scheduling calls in worker threads and serializing some flows via semaphores.

### 4.2 Base URL configuration

Facts:
- Defaults:
  - `default_web_base_url = https://artisan.plus`
  - `default_api_base_url = https://artisan.plus/api/v1`
- `normalize_server_url()`:
  - Accepts user-configured server URL.
  - Adds scheme if missing (`http://` for localhost/loopback, `https://` otherwise).
  - Strips trailing slash.
- `derive_service_base_urls()`:
  - If path already ends with `/api/v1`, keeps it as API path and removes suffix for web path.
  - Else appends `/api/v1` for API path.
- `set_server_base_url()` composes endpoint constants:
  - `/accounts/users/authenticate`
  - `/acoffees`
  - `/aroast`
  - `/aschedule/lock`
  - `/notifications`
  - `/roasts/{roast_id}/upload-profile`
  - `/roasts/{roast_id}/profile/data`
  - `/roasts/references`

### 4.3 Request construction and headers

Facts:
- JSON body serialization is explicit:
  - `json.dumps(..., separators=(',', ':'), ensure_ascii=False).encode('utf8')`.
- Standard headers (when app window is available):
  - `user-agent: Artisan/<version> (<os>; <os_version>; <os_arch>)`
  - `Accept-Charset: utf-8`
  - Optional `Accept-Language` from UI locale (`xx-yy` form)
  - Optional `Authorization: Bearer <token>`
  - Optional `Accept-Encoding: deflate, compress, gzip`
- JSON POST/PUT adds:
  - `Content-Type: application/json; charset=utf-8`
  - `Idempotency-Key` only for POST.
- If compression enabled and JSON size exceeds `post_compression_threshold` (500 bytes), body is gzip-compressed and `Content-Encoding: gzip` is set.

### 4.4 Authentication and session handling

Facts:
- `authentify()` sends POST to `/accounts/users/authenticate` with `email` and `password`.
- Password source:
  - In-memory `config.passwd`, else keyring (`keyring.get_password(...)`).
- Successful auth expects JSON with nested token under `result.user.token`.
- Token + nickname are stored in shared config under semaphore (`QSemaphore`) protection.
- On logout/clear, token/password/account fields are reset and keyring entry may be removed.
- For authorized requests:
  - If response is `401`, connection layer triggers one re-auth (`authentify()`), then retries request once.

### 4.5 Timeouts and adaptive read-timeout behavior

Facts:
- Static config values:
  - `connect_timeout = 6s`
  - `read_timeout = 12s`
  - `read_timeout_max = 30s`
- Actual timeout tuple passed to requests calls: `(connect_timeout, current_read_timeout)`.
- Dynamic read-timeout adaptation:
  - On success, reduce current read timeout by 2s step down to minimum `read_timeout`.
  - On timeout exception, set current read timeout to `read_timeout_max`.

Inference:
- This acts as adaptive tolerance for temporary slow backend/network periods, then converges back to baseline after successful calls.

### 4.6 Retries

Facts:
- Transport-level retry:
  - Single retry after re-auth for `401` in `sendData`, `sendFile`, `getData`.
- Queue-level retries for roast sync uploads in `queue.Worker.task()`:
  - `queue_retries = 2`, so up to 3 attempts for items with `modified_at`.
  - Retry delay: `queue_retry_delay = 30s`.
  - For generic failures: sleep `2 * queue_retry_delay` before next try.
  - Special handling:
    - `409` -> stop retries.
    - `401` -> disconnect logic + decremented retries.
    - connection errors trigger disconnect and delay.

### 4.7 Error handling

Facts:
- Transport:
  - Catches `requests.exceptions.Timeout` and updates adaptive timeout state.
  - `getData()` returns `None` on timeout.
  - `sendData()` / `sendFile()` re-raise timeout exceptions.
- Auth path:
  - Distinguishes timeout, SSL, generic request exceptions, JSON decode errors.
  - On SSL error sends UI message `SSLError` and clears credentials.
- Queue/send callers often use `raise_for_status()` and then branch by status in exception paths.
- JSON parse helpers check `Content-Type` starts with `application/json` before decoding.

### 4.8 JSON serialization/deserialization

Facts:
- Outgoing JSON: manual `json.dumps` -> bytes.
- Incoming JSON:
  - multiple call sites use `response.json()` only when `content-type` is JSON-like.
  - decode errors are logged with char/line/col diagnostics.
- Some endpoints expect `204 No Content` as meaningful state (not always error).

### 4.9 File upload/download

Facts:
- Upload present:
  - Multipart POST in `sendFile()` (`files={field_name: (basename, fh)}`), default field name `file`.
  - Used for full roast profile upload to `/roasts/{roast_id}/upload-profile` from queue.
- Download present:
  - Roast data/profile JSON retrieval via GET `/aroast/{uuid}` with optional `?modified_at=...` in `sync.fetchServerUpdate()`.
- Additional profile data URL template exists (`/roasts/{roast_id}/profile/data`) but no direct use found in inspected runtime call sites.

### 4.10 Synchronous vs asynchronous behavior

Facts:
- HTTP calls are synchronous/blocking at `requests` call level.
- Non-blocking UI strategy:
  - stock update worker uses `QThread` and semaphores (`fetch_semaphore`).
  - queue uploader uses `QThread` worker and condition pause/resume.
  - notifications retrieval guarded by semaphore, triggered via `QTimer`.

Inference:
- Client design is synchronous I/O with thread-based isolation from GUI, not event-loop async HTTP.

### 4.11 Logging/debug output

Facts:
- Extensive `_log.debug/info/error/exception` usage around request lifecycle:
  - method entry, URL, status code, response size/time, retry events, decode problems.
- Sensitive payload caution exists (`sendData` intentionally avoids logging POST data body due to credentials risk).

## 5. Network/API behavior

Observed behavior from code (no live traffic capture in this investigation):

- Authentication flow:
  1. Load credentials (keyring/memory).
  2. POST `/accounts/users/authenticate`.
  3. Parse token and account limits/subscription payload.
  4. Store token; mark connected and start outbox queue.

- Stock/schedule pull:
  1. GET `/acoffees?today=<local-date>[&lsrt=<serverTime>]`.
  2. On `200` + success payload -> replace stock cache and update limits/schedule.
  3. On `204` -> no content/update path.

- Roast push:
  1. Queue roast JSON to `/aroast` POST.
  2. On success, update sync cache and possibly queue follow-up profile file upload.

- Profile upload:
  1. Resolve profile file path or serialize temp `.alog`.
  2. Multipart POST `/roasts/{roast_id}/upload-profile`.
  3. Cleanup temp file when flagged.

- Notifications pull:
  1. GET `/notifications` with optional machine filter.
  2. Filter unsupported notifications, sort by `added_on`, emit local notifications.

- Roast freshness sync:
  1. GET `/aroast/{uuid}?modified_at=<ms-epoch>`.
  2. `204` means server older/no newer data.
  3. `200` returns server newer data to apply.
  4. `404` may indicate deleted record; sync entry can be removed.

## 6. Data model mapping

| UI/code action | function/class | HTTP method | endpoint path | request fields | response fields | error behavior | dependency on cloud/backend version |
|---|---|---|---|---|---|---|---|
| Login/authentication | `plus.connection.authentify()` | POST | `/accounts/users/authenticate` | `email`, `password` JSON | expects `success`, `result.user.token`, user/account/limits fields | auth fail clears credentials; SSL/timeout/request exceptions handled distinctly | High: strict nested token contract (`result.user.token`) and account shape assumptions |
| Fetch stock + schedule snapshot | `plus.stock.Worker.fetch()` | GET | `/acoffees` | query: `today`, optional `lsrt` | expects `success`, `result` stock payload, account limits | `204` handled as empty/no update; timeout may yield disconnect path | High: stock payload schema + `lsrt` server behavior must match |
| Fetch notifications | `plus.notifications.retrieveNotifications()` | GET | `/notifications` | optional query `machine` | expects `success`, `result` list of notifications | decode/content errors logged; skipped if lock not acquired | Medium: expects list payload and fields like `added_on`, `not_for_artisan` |
| Upload roast summary/updates | `plus.queue.Worker.task()` via `connection.sendData()` | POST | `/aroast` | roast JSON diff/full record incl. `roast_id`, `modified_at`, optionally `date`, `amount`, other roast attrs | optional account state fields parsed from JSON | retries on queue policy; `409` stops retries; `401` triggers disconnect/re-auth pathways | High: relies on accepted incremental update semantics and returned account-state fields |
| Upload roast profile file | `plus.queue.Worker.task()` via `connection.sendFile()` | POST (multipart) | `/roasts/{roast_id}/upload-profile` | multipart file field `file` | status only (JSON optional) | if missing file -> user message; failures produce warning message after retries | High: endpoint exists only in compatibility mode (non-default server URL) and expects multipart field contract |
| Lock schedule after queueing | `plus.queue.sendLockSchedule()` + worker send | POST | `/aschedule/lock` | empty JSON body; query `today` | status only | retried through queue item loop; failures logged | Medium: depends on lock endpoint being idempotent/tolerant to retries |
| Fetch roast server update by UUID | `plus.sync.fetchServerUpdate()` | GET | `/aroast/{uuid}` | optional query `modified_at` (ms timestamp) | expects JSON with `result` roast record for `200` | `204` interpreted as server older; `404` may trigger sync deletion | High: relies on `200/204/404` semantic contract |
| Fetch roast references for machine/beans | `plus.stock.getReferencesFromAPI()` | GET | `/roasts/references` | optional query `coffee_hr_id`, `blend_hr_id`, `machine` | expects `data.items[]` with `id`, `reference_name`/`title` | fallback retry without coffee/blend filter if zero items | Medium-High: tied to specific `data.items` envelope and fallback semantics |
| Update completed roast weight/properties from UI | `plus.schedule.set_roasted_weight()` / `completed_items_selection_changed()` | POST | `/aroast` | delta JSON + `roast_id`, `modified_at` | primarily status-based success | on failure sends UI error “Updating completed roast properties failed” | High: depends on partial update behavior on same roast endpoint |

## 7. Roastlocal Cloud assumptions

Facts:
- Backend supports token auth and bearer authorization.
- Backend may return `204` as a normal no-content/no-newer-data state.
- Backend accepts incremental roast updates to the same `/aroast` endpoint used for full roast payloads.
- Backend supports idempotency key semantics at least tolerantly for POST (header always sent).
- Backend supports optional gzip-compressed JSON request bodies.
- Backend supports multipart profile upload endpoint (`/roasts/{roast_id}/upload-profile`) when using non-default server mode.

Inference:
- Client assumes backend compatibility with historical artisan.plus contracts; Roastlocal Cloud integration appears to preserve these contracts via adaptation.

## 8. Artisan compatibility assumptions

Facts:
- The client keeps its own local sync cache and uses `modified_at` timestamps to resolve synchronization decisions.
- Queue and worker behavior assumes transient connectivity and delayed retries rather than strict immediate consistency.
- Profile upload is treated as a second-stage operation after roast summary upload.
- Some payload fields are normalized/suppressed (`sync.suppress_zero_values`) before sending.

Inference:
- Compatibility depends on preserving both endpoint-level behavior and subtle state semantics (e.g., 204 meaning, modified_at comparison, server-side merge behavior).

## 9. Conflicts and contradictions

- Potential log message mismatch: in `connection.getData()`, branch comment/log says `session token outdated (404)` while code checks `status_code == 401`. This appears to be a wording inconsistency, not logic inconsistency.
- `profile_data_url_template` is defined in config but not used directly in inspected runtime calls; actual profile freshness sync uses `/aroast/{uuid}` path.
- `remote_profile_fetch_enabled()` currently equals `server_url != default_web_base_url`, which implies behavior gating by selected server, not by explicit capability negotiation.

## 10. Risks

- Contract fragility risk: nested JSON field assumptions (especially auth and stock payloads) can break client behavior if backend envelope changes.
- Status-code semantic risk: changing meaning of `204`/`404` in roast sync endpoints can silently desynchronize client logic.
- Retry/duplicate risk: queue retries + POST updates rely on backend idempotency/conflict strategy.
- Compression compatibility risk: if backend/proxy chain mishandles `Content-Encoding: gzip`, larger POST payloads may fail.
- Blocking risk under severe network issues: synchronous HTTP with long read timeouts can still tie up worker threads, though GUI remains mostly protected.

## 11. What must not be broken

- Bearer token issuance and acceptance flow (`/accounts/users/authenticate` + `Authorization: Bearer ...`).
- `/aroast` dual-use behavior for both full roast upload and incremental updates.
- `modified_at`-based conflict/sync semantics used by queue and sync cache.
- `204` no-content semantics on stock and roast-update fetch paths.
- Multipart profile upload endpoint and expected file field contract.
- Base URL derivation logic that maps user server URL to web + `/api/v1` API endpoints.

## 12. Owner questions

1. For Roastlocal Cloud, is `POST /aroast` guaranteed to remain backward-compatible for both full create and partial update payloads?
2. Is `204` guaranteed as the canonical "no newer roast data" response for `GET /aroast/{uuid}?modified_at=...`, or should client tolerate `304`/`200` alternatives?
3. Are gzip-compressed request bodies officially supported across all production ingress layers?
4. Is `Idempotency-Key` actually enforced server-side, or just tolerated? (Important for retry duplicate protection.)
5. Should `/roasts/{roast_id}/profile/data` be actively used by the client, or is `/aroast/{uuid}` the only supported read path for now?
6. Is profile upload intentionally enabled only for non-default server URLs, or should this gating be revisited for unified behavior?

## 13. Suggested next investigation

A focused endpoint contract validation pass against Roastlocal Cloud backend (without changing runtime code):
- enumerate real response envelopes and status-code matrix for all endpoints used above,
- compare against current client assumptions (especially auth payload nesting, `204` semantics, and `/aroast` update behavior),
- produce a compatibility-gap matrix (client assumption vs backend guarantee) under `docs/recovery/client-investigations/`.
