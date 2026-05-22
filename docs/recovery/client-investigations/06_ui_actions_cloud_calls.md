# Client Investigation: UI actions that trigger Roastlocal Cloud calls

## 1. Research question

Which Artisan client UI actions trigger Roastlocal Cloud calls?

## 2. Executive summary

Roastlocal Cloud calls are concentrated in the `src/plus/*` integration layer and are triggered by a mix of explicit user actions (login, scheduler update, register roast, completed-roast edits) and automatic background flows (post-login stock refresh, periodic sync queue processing, notification fetch).

The dominant runtime endpoint for production-critical roast/schedule operations is `/api/v1/aroast` (create/update/sync), with `/api/v1/acoffees` used for stock/schedule pull and `/api/v1/accounts/users/authenticate` used for session establishment. Scheduler UI interactions in `plus/schedule.py` are tightly coupled to these cloud calls.

## 3. Files inspected

- `src/plus/config.py`
- `src/plus/controller.py`
- `src/plus/connection.py`
- `src/plus/login.py`
- `src/plus/schedule.py`
- `src/plus/stock.py`
- `src/plus/sync.py`
- `src/plus/queue.py`
- `src/plus/notifications.py`
- `docs/recovery/client-investigations/03_http_network_layer.md`
- `docs/recovery/client-investigations/05_sync_import_export_workflows.md`

## 4. Facts from code

- Endpoint composition is centralized in `plus.config.set_server_base_url()`:
  - `auth_url = .../accounts/users/authenticate`
  - `stock_url = .../acoffees`
  - `roast_url = .../aroast`
  - `lock_schedule_url = .../aschedule/lock`
  - `notifications_url = .../notifications`
  - `profile_upload_url_template = .../roasts/{roast_id}/upload-profile`
  - `profile_data_url_template = .../roasts/{roast_id}/profile/data`
  - `references_url = .../roasts/references`
- Transport wrappers are in `plus.connection` (`sendData`, `sendFile`, `getData`) using synchronous `requests` calls.
- UI entry points are primarily in `plus/controller.py` and `plus/schedule.py` (`clicked.connect`, `triggered.connect`, dialog accept handlers).

## 5. Network/API behavior

| UI label/name | UI type | Code location (UI trigger) | Cloud endpoint called | Request purpose | Expected response | User-visible success/failure behavior | Production-critical |
|---|---|---|---|---|---|---|---|
| Plus toggle/login (toolbar plus state) | Button/toggle | `src/plus/controller.py` (`toggle()` -> `connect()` -> `authentify()`) | `POST /api/v1/accounts/users/authenticate` | Authenticate account and get bearer token/account state | JSON with `success`, `result.user.token` and account payload | Success: messages like “authentified”, “Connected to artisan.plus”; Failure: “Authentication failed” / “Couldn't connect...” | Yes |
| Login dialog `OK` | Dialog | `src/plus/login.py` (`accepted.connect(self.setCredentials)`), consumed in `plus_login()` then `controller.connect()` | `POST /api/v1/accounts/users/authenticate` | Submit credentials entered in dialog | Same as above | Success updates plus status; failure message shown via `sendmessageSignal` | Yes |
| Scheduler top-right `Update schedule` (`QToolButton`) | Button | `src/plus/schedule.py:2261-2277` (`sync_button.clicked.connect(self.trigger_stock_update)`) -> `stock.update()` | `GET /api/v1/acoffees` | Pull current stock + schedule snapshot | `200` JSON payload or `204` no update | Success refreshes scheduler lists; failures can lead to stale UI and disconnect/reconnect state | Yes |
| Scheduler “Register roast” (context menu on selected schedule item) | Context menu action | `src/plus/schedule.py` (`addToItemAction.triggered.connect(self.addLoadedProfileToSelectedScheduleItem)`) -> `register_roast()` | `POST /api/v1/aroast` | Link loaded roast/profile data to schedule item and push roast changes | HTTP success + optional JSON account state | Success updates selected/completed schedule state; failure message: “Register roast failed” | Yes |
| Completed roast property edits (weight/yield/color/moisture/density/notes/cupping score) | Inputs in scheduler completed panel | `src/plus/schedule.py` (`editingFinished.connect(...)` handlers -> changes pipeline -> `sendData`) | `POST /api/v1/aroast` | Push partial roast property updates for completed roast item | HTTP success; may include account fields | Success keeps completed item synced; failure message: “Updating completed roast properties failed” | Yes |
| “Task completed” flow (`task_weight` click) | Button | `src/plus/schedule.py:2445` (`task_weight.clicked.connect(self.taskCompleted)`) and registration flow to completed item | `POST /api/v1/aroast` (direct and/or queued) | Persist completion-related roast/schedule data | HTTP success | Success moves/updates task in scheduler and completed tab; failure leaves local state unsynced or shows update failure | Yes |
| Roast properties/save while plus is ON and roast is synced | Roast/profile screen action (save/edit) | `src/plus/controller.py` (`updateSyncRecordHash()`, queueing updates) -> queue worker | `POST /api/v1/aroast` (and retries) | Sync changed roast sync-record attributes to cloud | HTTP success or handled retry/error statuses | Mostly background; user may only notice status icon/messages on failures | Yes |
| Automatic post-login refresh | Automatic background sync | `src/plus/controller.py` (`QTimer.singleShot(2000, stock.update)`) | `GET /api/v1/acoffees` | Initial stock/schedule refresh after connect | `200`/`204` | Visible as scheduler/stock data appearing shortly after login | Yes |
| Automatic notifications pull | Automatic background sync | `src/plus/notifications.py` (`updateNotifications()` -> delayed `retrieveNotifications()`) | `GET /api/v1/notifications` | Retrieve pending cloud notifications | JSON list in `result` | Success: notifications shown via local notification manager; failure: logged, usually silent | Medium |
| Automatic queue worker upload (outbox) | Automatic background sync | `src/plus/queue.py` worker task loop | `POST /api/v1/aroast` and `POST /api/v1/aschedule/lock` | Flush queued roast updates and schedule-lock events | HTTP status + optional JSON | Mostly non-blocking; retries on transient errors; may affect eventual consistency if failing | Yes |
| Automatic server-freshness check for selected completed roast | Automatic-on-selection/background in scheduler | `src/plus/schedule.py` (`completed_items_selection_changed` path) -> `plus.sync.fetchServerUpdate()` | `GET /api/v1/aroast/{uuid}?modified_at=...` | Pull newer server version before editing/comparing completed roast | `200` newer data, `204` no newer, `404` missing | Success can apply remote updates in UI; failure can block certain completed-roast edits | Yes |
| Import/export-adjacent profile upload (non-default server mode) | Background follow-up to roast push | `src/plus/queue.py` via `connection.sendFile()` | `POST /api/v1/roasts/{roast_id}/upload-profile` | Upload full profile file after roast summary upload | HTTP success status | User-visible warnings on failure; roast summary may still be synced | High (for full compatibility mode), conditional |

## 6. Data model mapping

| Trigger family | Primary payload model | Notes |
|---|---|---|
| Auth/login | `{email, password}` | Token extracted from `result.user.token` |
| Stock/schedule refresh | Query params (`today`, optional `lsrt`) | Response drives scheduler item caches and stock state |
| Roast register/update/edit/sync | Roast/sync record over `/aroast` | Includes `roast_id`, `modified_at`, schedule link fields and roast property deltas |
| Notifications | Optional `machine` query | Response list filtered for Artisan-facing notifications |
| Profile upload | Multipart form (`file`) | Separate second-stage upload after roast summary |

## 7. Roastlocal Cloud assumptions

Facts:
- Backend preserves Artisan Plus endpoint contract and status semantics (`200/204/401/404/409` usage patterns).
- `/aroast` accepts both full and partial update semantics used by scheduler and sync queue.
- Account state fields may be included in various responses and are parsed to update client limits/notifications.

Inference:
- UI behavior in scheduler screens depends on response envelopes and status-code semantics as much as on endpoint availability.

## 8. Artisan compatibility assumptions

- Scheduler UX expects near-real-time freshness via `/acoffees` pull and selective `/aroast/{uuid}` checks.
- Completed-roast editing assumes a corresponding sync record exists; missing sync state can disable edit behavior.
- Queue-first design assumes transient offline periods and eventual retry-driven consistency.

## 9. Conflicts and contradictions

- `profile_data_url_template` is defined in config but this investigation found UI-triggered behavior dominated by `/aroast` and `/acoffees`; profile-data path is a specialized compatibility flow, not a common direct UI button action.
- Some UI labels reference artisan.plus wording, while server URL can be overridden for Roastlocal deployment; branding text and endpoint target can diverge.

## 10. Risks

- Breaking `/aroast` partial-update behavior would regress multiple UI actions at once (register roast, completed edits, sync).
- Schedule UX degrades quickly if `/acoffees` contract changes (empty lists, stale tasks, filter behavior confusion).
- Silent background failures (queue/notifications) can hide cloud divergence until later user actions.

## 11. What must not be broken

- Login/auth token contract (`/accounts/users/authenticate`).
- Scheduler manual refresh + post-login refresh (`/acoffees`).
- Register-roast and completed-roast edits (`/aroast`).
- Queue-driven eventual sync and schedule lock behavior (`/aroast`, `/aschedule/lock`).
- Conditional full profile upload path in compatibility mode (`/roasts/{id}/upload-profile`).

## 12. Owner questions

1. In current Roastlocal production, which UI actions must hard-fail with explicit user errors vs. allow silent queued retry (especially for completed roast edits)?
2. Is `/aschedule/lock` mandatory for current backend behavior, or only an optimization/hint?
3. Should profile upload (`/roasts/{id}/upload-profile`) be considered production-critical for Roastlocal now, or only desirable for parity?
4. Do you want explicit user-facing indication when background queue sync is delayed/failing repeatedly?
5. Is the `/notifications` channel actively used in production workflows or optional?

## 13. Suggested next investigation

Capture a sanitized UI-to-HTTP trace for one complete scheduler session (login -> update schedule -> register roast -> edit completed roast -> background queue flush), then validate each observed request/response envelope against current Roastlocal backend behavior.
