# Client Investigation: Roastlocal Cloud Integration Boundary in Modified Artisan Client

## 1. Research question
Where is the Roastlocal Cloud integration boundary inside the modified Artisan client?

## 2. Executive summary
The integration boundary is concentrated in `src/plus/` and consumed from `src/artisanlib/main.py` as a service adapter. The desktop core remains in `artisanlib`, while all cloud-facing HTTP, auth/session, queueing, sync diffs, stock/schedule fetches, notification fetches, and remote profile transfer are encapsulated in `plus` modules.

No runtime code in `src/` references the literal string `Roastlocal`; integration is implemented as an Artisan Plus-compatible contract (URL patterns, payload shape, sync rules), with server base URL override support allowing a Roastlocal-compatible backend.

## 3. Files inspected
- `src/plus/config.py`
- `src/plus/connection.py`
- `src/plus/queue.py`
- `src/plus/sync.py`
- `src/plus/roast.py`
- `src/plus/stock.py`
- `src/plus/schedule.py`
- `src/plus/notifications.py`
- `src/plus/controller.py`
- `src/plus/login.py`
- `src/plus/util.py`
- `src/artisanlib/main.py`
- `docs/recovery/client-investigations/01_client_repo_map.md` (for prior context only)

## 4. Facts from code
- Cloud integration namespace is `plus.*` (`src/artisanlib/main.py` imports `plus.config`, `plus.connection`, `plus.sync`, `plus.queue`, `plus.stock`, `plus.schedule`, etc.).
- Server URL is user-configurable and normalized in `plus.config.normalize_server_url()` and `plus.config.derive_service_base_urls()`.
- Default cloud targets are Artisan Plus URLs (`default_api_base_url = https://artisan.plus/api/v1`, `default_web_base_url = https://artisan.plus`).
- Endpoint constants are assembled centrally in `plus.config.set_server_base_url()`.
- HTTP primitives are centralized in `plus.connection`: `sendData()`, `sendFile()`, `getData()` with token auth, retries on 401, and timeouts.
- Upload/send operations are queued in `plus.queue` (`persistqueue.SQLiteQueue`), including deferred file upload (`profile_upload`).
- Bi-directional roast property sync logic is in `plus.sync` + `plus.roast` (sync record extraction, suppression defaults, diffing, applying server updates).
- Schedule and stock interaction are driven by `plus.stock.fetch()` and `plus.schedule` UI actions.
- Optional remote background profile download is in `ApplicationWindow.fetchRemoteBackgroundProfile()` (`main.py`) and calls `plus.connection.getData(plus.config.get_profile_data_url(UUID))`.

## 5. Network/API behavior

### 5.1 Base URLs
- `https://artisan.plus/api/v1` (default API)
- `https://artisan.plus` (default web)
- `https://buy.artisan.plus/` (default shop)
- Override path: user/server setting in UI login flow (`plus.login` + `plus.controller.connect`)

### 5.2 API endpoint paths (built in `plus.config.set_server_base_url`)
- `/accounts/users/authenticate` (`auth_url`)
- `/acoffees` (`stock_url`)
- `/aroast` (`roast_url`)
- `/aschedule/lock` (`lock_schedule_url`)
- `/notifications` (`notifications_url`)
- `/roasts/{roast_id}/upload-profile` (`profile_upload_url_template`)
- `/roasts/{roast_id}/profile/data` (`profile_data_url_template`)
- `/roasts/references` (`references_url`)

### 5.3 Query parameters observed
- `today=YYYY-MM-DD` for schedule-aware stock/lock calls
- `lsrt=<serverTime>` stock incremental schedule check
- `modified_at=<epoch_ms>` roast update fetch gating (`sync.fetchServerUpdate`)
- `coffee_hr_id`, `blend_hr_id`, `machine` for references lookup

### 5.4 Request builders
- `plus.connection.getHeaders()` builds UA, locale, optional `Authorization: Bearer <token>`, optional compression accept headers.
- `plus.connection.getHeadersAndData()` builds JSON headers, gzip payload, and `Idempotency-Key` for `POST`.
- `plus.connection.sendData()` performs JSON POST/PUT.
- `plus.connection.sendFile()` performs multipart upload.
- `plus.connection.getData()` performs GET with params.
- `plus.roast.getRoast()` builds roast payload from internal profile data and mapping rules.

### 5.5 Response parsers
- `plus.connection.authentify()` parses auth response (`success/result/user/token/account/...`).
- `plus.queue.get_response_json()` parses generic queue response JSON.
- `plus.util.extractAccountState()` parses account limits/notifications.
- `plus.stock.fetch()` parses stock payload (`success/result`).
- `plus.sync.fetchServerUpdate()` parses roast record update payload (`result`).
- `plus.notifications.retrieveNotifications()` parses notification list payload.
- `plus.stock.getReferencesFromAPI()` parses references payload (`data.items`) and normalizes IDs.

## 6. Data model mapping

### 6.1 Internal Artisan -> cloud payload adaptation
Primary mapper: `plus.roast.getTemplate()` + `plus.roast.getRoast()`
- `roastUUID` -> `id` -> `roast_id`
- `scheduleID` -> `s_item_id`
- `scheduleDate` -> `s_item_date`
- `start_weight` -> `amount`
- Internal units converted to kg/Celsius where required
- Blend object trimmed (`trimBlendSpec`) before upload
- Defaults/null suppression for sync payload (`sync_record_*_supressed_attributes`)

### 6.2 Cloud -> internal Artisan adaptation
Primary applier: `plus.sync.applyServerUpdates()`
- Reconstructs suppressed defaults (`0`, `50`, `''`) before writing into local fields
- Applies cloud values to qmc fields (weights, batch metadata, coffee/blend/store, machine, notes, cupping, density, moisture, etc.)
- Updates dirty/title/UI state after applying server updates

### 6.3 Compatibility/adaptation hotspots
- `plus.roast` (serialization + naming/unit adaptation)
- `plus.sync` (diff/suppress/reconstruct/apply)
- `plus.stock` (stock/schedule structures and references lookup fallback)
- `plus.schedule` (UI edit to partial sync-record updates)

## 7. Roastlocal Cloud assumptions
Facts:
- Cloud contract is assumed to be Plus-compatible (`/api/v1/...`, auth semantics, roast/stock/schedule/notification payload shapes).
- Non-default server URL enables profile upload/download features (`profile_upload_enabled`, `remote_profile_fetch_enabled`).

Inference:
- Roastlocal Cloud boundary likely preserves this Plus contract and/or provides a compatibility facade.

## 8. Artisan compatibility assumptions
- Existing Plus sync mechanics (suppression rules, bidirectional fields, queue retries, sync cache) are treated as canonical client behavior.
- Scheduler and completed-roast edits depend on server acceptance of partial roast updates via `/aroast` POST.
- Local caches (`stock`, `sync`, `outbox`, `completed`, `prepared`, `hidden`) are part of resilience/offline compatibility behavior.

## 9. Conflicts and contradictions
- Naming conflict: runtime modules consistently describe service as `artisan.plus`, while repository context/documentation describes Roastlocal compatibility usage.
- No runtime literal `Roastlocal` references were found in `src/`; only documentation mentions Roastlocal.

## 10. Risks
- Contract drift risk if backend deviates from Plus endpoint names or payload fields.
- Suppression/default reconstruction mismatch risk (e.g., `None` vs `0/50/''`) causing silent semantic divergence.
- Scheduler edit flows depend on sync cache presence; missing sync cache blocks editable completed items.
- Remote profile fetch is optional and gated by non-default server URL, so behavior differs across deployments.

## 11. What must not be broken
- Auth/session lifecycle with token refresh and reconnect behavior.
- Outbox queue semantics for roast upload and delayed file upload.
- Sync record field mapping and default suppression/reconstruction rules.
- Stock/schedule fetch cadence and schedule UI update wiring.
- Completed-roast edit save path (`schedule.py` -> `/aroast` partial update).
- Optional remote background profile fetch path for UUID-linked templates.

## 12. Owner questions
1. For Roastlocal production, is full endpoint-level Plus parity guaranteed for all routes listed above, or only a subset with compatibility shims?
2. Should `profile_upload_enabled()` / `remote_profile_fetch_enabled()` remain tied to non-default server URL, or be explicit feature flags per environment?
3. Is `references_url` (`/roasts/references`) required in all Roastlocal environments, including local/staging?
4. Are there backend-side differences for notification/reset semantics that could break `plus.notifications.retrieveNotifications()` assumptions?
5. Should the client continue storing and using `plus_*` naming in persisted profile/settings fields as long-term compatibility identifiers?

## 13. Suggested next investigation
Perform investigation 03 focused only on API contract conformance: for each endpoint above, map required request/response field sets, optional fields, default/null semantics, and status-code behavior used by this client.
