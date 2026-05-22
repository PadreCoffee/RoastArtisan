# Client Investigation: Final compatibility picture between the modified Artisan client and Roastlocal Cloud

## 1. Research question

What is the final compatibility picture between the modified Artisan client and Roastlocal Cloud?

## 2. Executive summary

The modified client is not integrated with Roastlocal Cloud through Roastlocal-native domain APIs. Its production-critical compatibility boundary is an **Artisan Plus-compatible HTTP and sync contract** implemented by the client in `src/plus/*` and consumed by the desktop runtime in `src/artisanlib/main.py`.

The practical compatibility picture is:

- the client core remains Artisan-centric;
- all cloud traffic is routed through Plus-shaped endpoints and payloads;
- Roastlocal Cloud must preserve a narrow but strict set of route names, status semantics, and field envelopes;
- some areas already contain explicit adaptation logic for Roastlocal-specific backend behavior;
- some behaviors still reflect historic Artisan/Artisan Plus assumptions and therefore remain unsafe to change on the backend without coordinated client changes.

The most critical compatibility surface is `/api/v1/aroast` plus its related read/upload routes. The second most critical surface is `/api/v1/accounts/users/authenticate` and `/api/v1/acoffees`. Traffic evidence confirms live use of `authenticate`, `acoffees`, `roasts/references`, `aroast`, `roasts/{id}/profile/data`, and `roasts/{id}/upload-profile` in a real capture. `aschedule/lock` and `notifications` are still referenced by code and therefore cannot be classified as dead code only because they were absent from one capture.

No separate cloud investigation reports were found in this repository during this pass. This synthesis therefore relies on:

- current client code,
- existing client investigation reports,
- sanitized traffic artifacts.

## 3. Files inspected

### Prior client investigations

- `docs/recovery/client-investigations/01_client_repo_map.md`
- `docs/recovery/client-investigations/02_cloud_integration_boundary.md`
- `docs/recovery/client-investigations/03_http_network_layer.md`
- `docs/recovery/client-investigations/04_client_data_model_mapping.md`
- `docs/recovery/client-investigations/05_sync_import_export_workflows.md`
- `docs/recovery/client-investigations/06_ui_actions_cloud_calls.md`
- `docs/recovery/client-investigations/07_config_auth_session.md`
- `docs/recovery/client-investigations/08_error_handling_offline_retry.md`
- `docs/recovery/client-investigations/09_traffic_capture_plan.md`
- `docs/recovery/client-investigations/10_traffic_analysis.md`
- `docs/recovery/client-investigations/traffic/traffic_summary_artisan_client.md`

### Current code re-checked for synthesis

- `src/plus/config.py`
- `src/plus/connection.py`
- `src/plus/roast.py`
- `src/plus/sync.py`
- `src/plus/stock.py`
- `src/plus/queue.py`
- `src/plus/schedule.py`
- `src/artisanlib/main.py`

### Cloud investigation availability

- No dedicated backend/cloud investigation reports were found under `docs/recovery/cloud-investigations/` or equivalent recovery paths during this pass.

## 4. Facts from code

### 4.1 Client-side compatibility boundary

Facts:

- The cloud boundary is centered in `src/plus/*`, not in the general `artisanlib` domain code.
- `src/plus/config.py:191-233` derives one web base URL and one `/api/v1` base URL, then hard-wires the current compatibility routes:
  - `/accounts/users/authenticate`
  - `/acoffees`
  - `/aroast`
  - `/aschedule/lock`
  - `/notifications`
  - `/roasts/{roast_id}/upload-profile`
  - `/roasts/{roast_id}/profile/data`
  - `/roasts/references`
- `src/plus/config.py:220-225` enables profile upload and remote profile fetch only when `server_url != default_web_base_url`.
- `src/plus/connection.py:153-199` expects successful auth JSON to include `success`, `result.user.token`, and account/user metadata under `result.user`.
- `src/plus/connection.py:327-366` always adds bearer auth when a token exists, adds `Idempotency-Key` on `POST`, and may gzip-compress larger JSON bodies.
- `src/plus/connection.py:369-521` automatically retries one time after `401` for `POST`, multipart upload, and `GET`.
- `src/plus/roast.py:140-142` sends both `s_item_id` and `s_item_date`.
- `src/plus/roast.py:296-306` converts local `id` to `roast_id` and `start_weight` to `amount`.
- `src/plus/roast.py:362-389` sends `coffee`, `blend`, and `location` with explicit `None` values to clear server-side state.
- `src/plus/sync.py:316-327` suppresses default values (`0`, `50`, `''`) to `None` before sync.
- `src/plus/sync.py:455-465` reconstructs suppressed defaults on inbound updates.
- `src/plus/sync.py:538-615` expects inbound `location`, `coffee`, and `blend` as objects, not scalars.
- `src/plus/sync.py:638-646` documents that `s_item_date` is not stored or returned by the server.
- `src/plus/sync.py:787-847` uses `GET /aroast/{uuid}?modified_at=...` with `204`, `404`, and `200` carrying distinct sync meanings.
- `src/plus/stock.py:243-255` expects `/acoffees` to return `success` plus `result`.
- `src/plus/stock.py:267-273` treats `204` from `/acoffees` as a valid no-content/no-change path.
- `src/plus/stock.py:1815-1835` expects `/roasts/references` to return `data.items[]` and includes a fallback retry without coffee/blend filters because backend linkage may actually depend on `green_bean_id`.
- `src/plus/queue.py:216-305` uploads roast summary first, then queues a second-stage profile upload when enabled.
- `src/plus/queue.py:338-362` treats `401` as retryable/reconnect-worthy and `409` as non-retryable.
- `src/plus/schedule.py:3141-3170` and `src/plus/schedule.py:3560-3578` use `POST /aroast` for completed-roast edits, not a separate update route.
- `src/artisanlib/main.py:14100-14139` fetches remote profile data from `/roasts/{id}/profile/data` and accepts payloads shaped as `result`, `data`, or a direct dict, but still requires `timex`, `temp1`, and `temp2`.

### 4.2 Runtime shape of compatibility

Facts:

- The client does not negotiate capabilities with the backend. Compatibility is inferred from route existence and payload behavior.
- The client preserves a durable outbox and local sync/register caches, so cloud compatibility includes offline and retry behavior, not just happy-path API responses.
- The same roast lifecycle is split across two channels:
  - summary/properties sync through `/aroast`
  - full profile transport through `/roasts/{id}/upload-profile`

Inference:

- Roastlocal Cloud currently acts as a compatibility target by exposing or emulating this Plus contract, not by replacing it with a new client-facing contract.

## 5. Network/API behavior

### 5.1 Backend routes that must remain stable

| Route | Method(s) | Client usage | Stability level | Evidence |
|---|---|---|---|---|
| `/api/v1/accounts/users/authenticate` | `POST` | login, reconnect, 401 recovery | Critical | `src/plus/config.py:204`, `src/plus/connection.py:153-199`, traffic observed |
| `/api/v1/acoffees` | `GET` | stock + schedule snapshot, post-login refresh, periodic refresh | Critical | `src/plus/config.py:205`, `src/plus/stock.py:243-255`, traffic observed |
| `/api/v1/aroast` | `POST` | roast create/update, scheduler edits, background sync queue | Critical | `src/plus/config.py:206`, `src/plus/queue.py:261-305`, `src/plus/schedule.py:3149-3154`, traffic observed |
| `/api/v1/aroast/{uuid}` | `GET` | server freshness check, inbound sync application | Critical | `src/plus/sync.py:781-847`, traffic observed |
| `/api/v1/roasts/{id}/upload-profile` | `POST multipart` | second-stage full profile upload | High | `src/plus/config.py:209`, `src/plus/queue.py:216-260`, traffic observed |
| `/api/v1/roasts/{id}/profile/data` | `GET` | remote background/reference profile fetch | High | `src/plus/config.py:210`, `src/artisanlib/main.py:14100-14139`, traffic observed |
| `/api/v1/roasts/references` | `GET` | reference discovery/filtering | High | `src/plus/config.py:211`, `src/plus/stock.py:1815-1835`, traffic observed heavily |
| `/api/v1/aschedule/lock` | `POST` | queue-driven schedule lock action | Medium-High | `src/plus/config.py:207`, `src/plus/queue.py:306-313`, code only in current evidence set |
| `/api/v1/notifications` | `GET` | background notifications | Medium | `src/plus/config.py:208`, prior investigations, code only in current evidence set |

### 5.2 Request/response contracts that must remain stable

| Surface | Current client expectation | Why unsafe to change |
|---|---|---|
| Auth success envelope | `success=true`, `result.user.token`, `result.user.account._id`, optional account limit data | Login, reconnect, identity persistence, account scoping all depend on this nesting |
| Auth failure semantics | `401`/`404`-style auth failures handled via existing client logic | Different status families could break reconnect diagnostics and error paths |
| `/acoffees` response | JSON with `success` and `result`; `204` allowed for no-change path | Scheduler and stock cache refresh logic depend on this exact interpretation |
| `/aroast` write response | HTTP success plus optional JSON account-state metadata | Queue success, limits refresh, and follow-up profile upload sequencing depend on it |
| `/aroast/{uuid}` freshness semantics | `200` = newer data payload, `204` = no newer data, `404` = likely missing/deleted record | Sync cache maintenance and completed-roast editability depend on these meanings |
| `/roasts/references` response | `data.items[]` with `id` and `reference_name` or `title` | Reference selector UI normalizes only this shape |
| `/roasts/{id}/profile/data` payload | Accepts `result`, `data`, or direct dict, but must include `timex`, `temp1`, `temp2` | Remote background/reference loading fails without these arrays |
| Multipart profile upload | field name `file` | Server-side upload parser must tolerate this exact field name |
| Write-body compression | gzip-compressed JSON may be sent for larger payloads | Ingress/proxy/backend must continue to accept `Content-Encoding: gzip` |
| Idempotency header | `Idempotency-Key` always sent on `POST` | Retry duplicate protection may rely on at least tolerant handling |

### 5.3 Unsafe-to-change fields and behaviors

Unsafe to change without a coordinated client release:

- `result.user.token`
- `result.user.account._id`
- `roast_id`
- `modified_at`
- `amount`
- `s_item_id`
- `coffee`, `blend`, `location` null-clearing semantics
- `data.items` in `/roasts/references`
- `timex`, `temp1`, `temp2` in `/profile/data`
- `204` meaning on `/acoffees` and `/aroast/{uuid}`
- `404` meaning on `/aroast/{uuid}`
- multipart field name `file`

### 5.4 Traffic-confirmed compatibility picture

Facts from `docs/recovery/client-investigations/traffic/traffic_summary_artisan_client.md`:

- real traffic used:
  - `POST /api/v1/accounts/users/authenticate`
  - `GET /api/v1/acoffees`
  - `GET /api/v1/roasts/references`
  - `GET /api/v1/roasts/{id}/profile/data`
  - `GET /api/v1/aroast/{uuid}`
  - `POST /api/v1/aroast`
  - `POST /api/v1/roasts/{id}/upload-profile`
- `/roasts/references` was the most frequent observed endpoint in the capture.
- one `401 Unauthorized` auth response was observed; the rest of the main captured compatibility routes were `200 OK`.

Inference:

- The live compatibility surface is not theoretical. The current client actively exercises the exact Plus-shaped routes above against a Roastlocal-hosted backend.

## 6. Data model mapping

### 6.1 Artisan concepts mapped to Roastlocal Cloud concepts

| Artisan/client concept | Cloud contract representation | Notes |
|---|---|---|
| roast UUID | `roast_id` | Canonical identity bridge for sync and upload |
| schedule item UUID | `s_item_id` | Links roast to schedule/completed-item workflows |
| schedule item date | `s_item_date` outbound only | Sent by client, not stored/returned by server per `src/plus/sync.py:638-646` |
| input weight | `amount` in kg | Client converts local unit to kg |
| output weight | `end_weight` in kg | Client converts both directions |
| defects weight | `defects_weight` in kg | Client converts both directions |
| coffee selection | outbound scalar `coffee=<hr_id>`; inbound object `coffee.{hr_id,label}` | Explicit adaptation mismatch between write and read shape |
| blend selection | outbound trimmed blend object; inbound detailed blend object | Client reconstructs local blend spec from server object |
| storage/location | outbound scalar `location=<hr_id>`; inbound object `location.{hr_id,label}` | Also cleared automatically when neither coffee nor blend is set |
| roast notes | `notes` | Direct property sync |
| cupping notes | `cupping_notes` | Direct property sync |
| cupping score | `cupping_score` | Default `50` is suppressed client-side |
| batch metadata | `batch_number`, `batch_prefix`, `batch_pos` | Bidirectional summary sync |
| machine/setup | `machine`, `setup` | Summary sync, also used in reference lookup |
| phase summary | flat fields such as `TP_time`, `DRY_time`, `FCs_time`, temperature fields | Derived summary, not raw event timeline |
| full profile curves/events | uploaded via `.alog` profile file | Not carried fully in `/aroast` summary JSON |

### 6.2 Places where client logic still follows Artisan assumptions

- The runtime remains centered on local Artisan profile state and `qmc` fields.
- The client assumes default suppression/reconstruction rules (`0`, `50`, `''`) as part of sync identity, not as an optional optimization.
- Completed-roast editability depends on the local sync-record game and sync cache presence, not only on backend truth.
- Full roast semantics are still split between:
  - summary fields the client knows how to normalize,
  - raw profile content carried by `.alog`.
- Profile analytics concepts such as derived phase metrics are computed locally and pushed outward as derived values.

### 6.3 Places where client already adapts to Roastlocal Cloud

- Custom server URL normalization and `/api/v1` derivation allow Roastlocal-hosted targets.
- Inbound profile data fetch accepts `result`, `data`, or direct-dict envelopes.
- Reference lookup retries without coffee/blend filters because backend linkage may rely on `green_bean_id`.
- Outbound coffee/location writes are scalar IDs; inbound reads tolerate richer objects.
- Queue/reconnect logic assumes temporary backend/network failures and keeps local roasting viable offline.

## 7. Roastlocal Cloud assumptions

### 7.1 Classification of current behavior

| Behavior | Classification | Basis |
|---|---|---|
| Plus route names under `/api/v1` | Required by current Roastlocal Cloud backend compatibility layer | Current client code and observed traffic |
| Nested auth response with `result.user.token` | Required by current backend compatibility layer | Client auth parser is strict |
| `/aroast` dual use for create and partial update | Required by current backend compatibility layer | Multiple UI and queue paths depend on same route |
| Default suppression/reconstruction (`0/50/'' <-> null`) | Required by Artisan client behavior | Implemented entirely in client sync logic |
| Scalar outbound `coffee/location` but object inbound `coffee/location` | Bridge/adaptation logic | Client write/read paths already diverge |
| Reference fallback without coffee/blend filters | Bridge/adaptation logic | Explicit backend linkage mismatch noted in code |
| Separate profile upload after summary upload | Required by current compatibility behavior | Queue sequencing depends on it |
| `profile_upload_enabled()` and `remote_profile_fetch_enabled()` tied to non-default server URL | Temporary compatibility workaround or deployment convention, not a robust capability model | Gating is implementation-based, not negotiated |
| `s_item_date` sent but not returned | Temporary compatibility artifact | Client comment says server does not persist it |
| `/notifications` and `/aschedule/lock` | Still active compatibility surface unless disproven | Present in code; absence in one capture is insufficient to mark unused |

### 7.2 Backend-facing assumptions the client currently makes

Facts:

- Roastlocal Cloud tolerates or supports gzip-compressed JSON writes.
- Roastlocal Cloud tolerates or supports `Idempotency-Key` on `POST`.
- Roastlocal Cloud uses `modified_at` as the authoritative roast freshness field.
- Roastlocal Cloud treats `204` as a business-meaningful no-update state, not just a transport-level empty response.

Inference:

- If Roastlocal wants to evolve away from these behaviors, it needs either a compatibility facade or a coordinated versioned client transition.

## 8. Artisan compatibility assumptions

Facts:

- The client remains primarily an Artisan desktop application with a Plus-style cloud adapter attached.
- Core roast/profile logic still originates locally and is only partially normalized into cloud summary fields.
- The sync model assumes a local file, local timestamp, local cache, and local retry queue as normal operating state.
- The client can continue local roast work even when the cloud is unavailable, then replay later.

Implication:

- “Compatibility” here means preserving current Artisan behavior while allowing Roastlocal Cloud to accept and return enough state to keep the client operational. It does not mean the backend may redefine the workflow around backend-native abstractions without protecting the Plus facade.

## 9. Conflicts and contradictions

1. **Coffee vs GreenBean semantics**
   - The roast payload uses `coffee`.
   - Reference lookup fallback explicitly suggests backend linkage may really be `green_bean_id`.
   - This is a documented semantic mismatch, not a solved shared glossary.

2. **Schedule date mismatch**
   - The client sends `s_item_date`.
   - `src/plus/sync.py:638-646` states the server does not store or return it.
   - This means outbound data and inbound truth are asymmetric.

3. **Summary JSON vs full roast profile scope**
   - `/aroast` contains summary and selected metadata.
   - Full curve/control/event detail still travels through profile upload and profile-data fetch flows.
   - Treating `/aroast` as the complete roast truth would be incorrect.

4. **Branding vs deployment reality**
   - Runtime naming remains `artisan.plus`-oriented.
   - Operational target may be Roastlocal Cloud at a custom URL.
   - Branding and protocol target are no longer the same thing.

5. **Capability gating by server URL**
   - Full profile upload/fetch is enabled by “non-default server URL” rather than an explicit server capability flag.
   - That is a compatibility shortcut, not a robust contract.

6. **Observed traffic vs full code surface**
   - `aschedule/lock` and `notifications` were not seen in one capture.
   - Code still references them, so they cannot be classified as dead without broader evidence.

## 10. Risks

### 10.1 Compatibility risks

- Auth-envelope drift would immediately break login and reconnect flows.
- Any change to `/aroast` partial-update semantics would break queue sync, scheduler edits, and completed-roast updates together.
- Changing `204` or `404` behavior on `/aroast/{uuid}` would destabilize sync cache and completed-roast edit behavior.
- Changing `data.items` in `/roasts/references` would visibly break reference lookup UX.
- Removing multipart profile upload while keeping `/aroast` only would create incomplete roast fidelity for workflows relying on full profile data.

### 10.2 Data-model risks

- Coffee/GreenBean/Lot semantics are still not fully harmonized across client and backend.
- Scalar outbound vs object inbound shapes for `coffee`, `blend`, and `location` are fragile.
- Suppressed default handling means “missing field” and “explicit default” are not interchangeable.

### 10.3 Operational risks

- Queue discard and retry policy can eventually drop old unsent items during prolonged outages.
- Profile summary upload can succeed while full profile upload fails, creating partially synchronized backend state.
- Sync cache corruption or missing sync entries can make scheduler items uneditable even when backend data exists.

## 11. What must not be broken

- The client-side compatibility boundary in `src/plus/*`.
- Base URL derivation from one configured server URL into one web base and one `/api/v1` API base.
- `POST /accounts/users/authenticate` response nesting, especially `result.user.token`.
- `GET /acoffees` schedule/stock snapshot behavior, including `today` and `lsrt` usage.
- `POST /aroast` dual role for new roast sync and partial property updates.
- `GET /aroast/{uuid}?modified_at=...` status semantics (`200`, `204`, `404`).
- Explicit `None` clearing behavior for `coffee`, `blend`, and `location`.
- Kg unit conversions for `amount`, `end_weight`, and `defects_weight`.
- Default suppression/reconstruction semantics for zero, fifty, and empty string values.
- `/roasts/references` response envelope and machine fallback behavior.
- `/roasts/{id}/upload-profile` multipart upload contract.
- `/roasts/{id}/profile/data` ability to return usable `timex/temp1/temp2` profile data.
- Durable outbox and sync cache behavior that lets local roasting continue while offline.

## 12. Owner questions

### 12.1 Owner decisions needed

1. Is Roastlocal Cloud committed to preserving the current Plus-compatible route surface as the production contract for this client, or do you want a versioned replacement strategy?
2. Do you want `profile_upload_enabled()` and `remote_profile_fetch_enabled()` to remain implicitly tied to “non-default server URL,” or should this become an explicit backend capability contract?
3. What is the authoritative backend glossary and mapping rule for:
   - `coffee`
   - `green_bean`
   - `location`
   - `lot`
4. Should `s_item_date` be persisted server-side, ignored formally, or removed from the client contract in a future coordinated change?
5. Is `204` the canonical and guaranteed “no newer data / no schedule change” status for all relevant endpoints, or should the client eventually support alternate semantics?
6. Is `409` on `/aroast` always intended to be terminal/non-retryable, or are there known conflict cases that should later merge/retry?
7. Are `/notifications` and `/aschedule/lock` required production surfaces, optional surfaces, or legacy surfaces that the backend plans to retire?
8. Is full profile upload considered mandatory for production compatibility today, or only best-effort parity on top of `/aroast` summary sync?

### 12.2 Recommended backend docs updates

- Publish one compatibility contract page listing every currently required client route under `/api/v1`.
- Document auth response shape exactly, including `result.user.token`, `result.user.account._id`, and limit/notification fields if returned.
- Document `/aroast` in two modes:
  - full roast/summary upload
  - partial property update
- Document `/aroast/{uuid}` status semantics explicitly:
  - `200`
  - `204`
  - `404`
- Document `/roasts/references` response envelope as `data.items[]` and clarify the Coffee vs GreenBean lookup rule.
- Document `/roasts/{id}/upload-profile` as a second-stage upload, including multipart field name `file`.
- Document `/roasts/{id}/profile/data` minimum required payload keys (`timex`, `temp1`, `temp2`).
- Document whether gzip-compressed JSON request bodies and `Idempotency-Key` are officially supported or merely tolerated.

### 12.3 Recommended client docs updates

- Add one client-facing compatibility boundary doc that states explicitly: Roastlocal Cloud integration is currently implemented as an Artisan Plus-compatible contract in `src/plus/*`.
- Document that `/aroast` is not the whole roast record; full profile fidelity may still depend on `.alog` upload/fetch.
- Document outbound vs inbound shape differences for `coffee`, `blend`, and `location`.
- Document default suppression/reconstruction rules so backend and client teams do not “clean up” them independently.
- Document that `s_item_date` is outbound-only in current behavior.
- Document that `profile_upload_enabled()` and `remote_profile_fetch_enabled()` currently depend on non-default server selection.
- Add one glossary section aligning Artisan terms with Roastlocal Cloud terms and highlighting open ambiguities.

## 13. Suggested next investigation

The next narrow investigation should be a **backend contract validation pass** that does not change runtime code and produces one field-level compatibility matrix for the currently live endpoints:

- `/accounts/users/authenticate`
- `/acoffees`
- `/aroast`
- `/aroast/{uuid}`
- `/roasts/references`
- `/roasts/{id}/upload-profile`
- `/roasts/{id}/profile/data`
- `/aschedule/lock`
- `/notifications`

That pass should answer three unresolved questions that this synthesis cannot settle from client-side evidence alone:

1. Which behaviors are guaranteed by Roastlocal Cloud today versus merely tolerated?
2. Which Plus-era fields/routes are intentional long-term compatibility surfaces versus temporary shims?
3. Which semantics should be written down as source-of-truth backend documentation before any cleanup or renaming work begins?
