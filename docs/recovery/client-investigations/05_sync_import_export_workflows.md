# Client Investigation: Sync, import, export, upload, and download workflows between modified Artisan client and Roastlocal Cloud

## 1. Research question

What sync, import, export, upload, and download workflows exist between the modified Artisan client and Roastlocal Cloud?

## 2. Executive summary

The production cloud integration is implemented through `src/plus/*` as an Artisan Plus-compatible API contract, with server URL override allowing Roastlocal-compatible backend usage. Core cloud workflows include:
- stock/schedule fetch (`/acoffees`),
- roast summary upload and sync (`/aroast`),
- delayed full profile file upload (`/roasts/{roast_id}/upload-profile`),
- remote profile data download for background/template use (`/roasts/{roast_id}/profile/data`),
- references/profile candidates lookup (`/roasts/references`),
- bidirectional partial property synchronization via sync records.

QC/cupping interactions are present and synced as roast properties (`cupping_score`, `cupping_notes`) via `/aroast` and server update fetches. Profile compare is local visualization logic and is not a direct cloud workflow.

Import/export of `.alog`/JSON/CSV is local file workflow in `artisanlib/main.py`; cloud upload of full profile is a separate multipart workflow triggered after roast summary upload when enabled.

## 3. Files inspected

- `src/plus/config.py`
- `src/plus/connection.py`
- `src/plus/controller.py`
- `src/plus/sync.py`
- `src/plus/stock.py`
- `src/plus/roast.py`
- `src/plus/queue.py`
- `src/plus/schedule.py`
- `src/artisanlib/main.py`
- `src/artisanlib/comparator.py`
- `src/artisanlib/util.py` (indirect via usage in flows)

## 4. Facts from code

- Cloud endpoints are constructed in `plus.config.set_server_base_url()`:
  - `stock_url = .../acoffees`
  - `roast_url = .../aroast`
  - `profile_upload_url_template = .../roasts/{roast_id}/upload-profile`
  - `profile_data_url_template = .../roasts/{roast_id}/profile/data`
  - `references_url = .../roasts/references`
- Full profile upload and remote profile fetch are gated:
  - `profile_upload_enabled()` is `True` only for non-default server URL.
  - `remote_profile_fetch_enabled()` is `True` only for non-default server URL.
- Roast payload transformation is done in `plus.roast.getRoast()` / `getTemplate()`:
  - local profile fields are normalized into cloud roast fields,
  - weights are converted to kg,
  - sync record suppresses default values (0, 50, empty string) with reconstruction logic in `plus.sync`.
- Queue worker (`plus.queue`) sends roast summary first, then optionally queues multipart full-profile upload.
- Server-to-client synchronization uses `plus.sync.fetchServerUpdate()` and `applyServerUpdates()`.

## 5. Network/API behavior

| Workflow | Endpoint(s) | Method | Direction | Response handling |
|---|---|---|---|---|
| Stock/schedule fetch | `/acoffees?today=...&lsrt=...` | GET | Cloud -> Client | 200 JSON updates stock cache; 204 treated as no fresh content; connection state updated |
| Roast upload / sync update | `/aroast` | POST (also PUT in generic sender) | Client -> Cloud | Success updates sync cache/hash; errors retried via queue policy |
| Roast property update fetch | `/aroast/{uuid}?modified_at=...` | GET | Cloud -> Client | 200 JSON applies sync record updates; 204 = server older/no update; 404 may remove sync key |
| Full profile file upload | `/roasts/{roast_id}/upload-profile` | POST multipart | Client -> Cloud | Triggered after roast summary success when enabled; failure reported separately |
| Remote profile data download | `/roasts/{roast_id}/profile/data` | GET | Cloud -> Client | 200 JSON validated for `timex/temp1/temp2`, serialized to temp `.alog` and registered |
| References fetch | `/roasts/references` | GET | Cloud -> Client | 200 JSON `data.items` parsed; fallback retry without coffee/blend filter |

Connection layer behavior (`plus.connection`):
- Adds bearer auth token.
- Retries once on `401` by re-authentication.
- Uses dynamic read timeout (increase on timeout, reduce on success).
- On timeout in `getData()`, returns `None` (callers may disconnect).

## 6. Data model mapping

### 6.1 Local profile -> cloud roast/sync record

- Entry: `plus.roast.getRoast()`
- Key mapped fields:
  - `roastUUID` -> `roast_id`
  - input weight -> `amount` (kg)
  - output weight -> `end_weight` (kg)
  - defects weight -> `defects_weight` (kg)
  - schedule link -> `s_item_id` / `s_item_date`
  - coffee/blend/location references
  - notes, cupping score, cupping notes
  - selected computed/environmental fields

### 6.2 Cloud sync record -> local mutable roast properties

- Entry: `plus.sync.applyServerUpdates()`
- Updates include:
  - batch metadata (`batch_number`, `batch_prefix`, `batch_pos`, label)
  - store/coffee/blend assignment
  - machine, notes
  - `cupping_score`, `cupping_notes`
  - roast moisture/density/color and selected weight fields
- Missing suppressed fields are reconstructed to defaults (0 / 50 / empty string) before apply.

## 7. Roastlocal Cloud assumptions

- Current integration assumes backend compatibility with Artisan Plus route shapes and payload semantics (`/acoffees`, `/aroast`, `/roasts/...`).
- References API is assumed to return `data.items` with `id` and `reference_name` or `title`.
- Roast update endpoint is assumed to support `modified_at` gating and return newer record including `modified_at`.
- Profile data endpoint is assumed to return profile-like JSON with at least `timex`, `temp1`, `temp2`.

## 8. Artisan compatibility assumptions

- Sync record hash (`plus_sync_record_hash`) embedded in profile is used to detect offline local edits.
- UUID/path register and sync shelve caches are part of normal operation and recovery.
- Full profile upload is secondary to roast summary upload; summary may succeed while full profile transfer fails.
- Comparator (`artisanlib/comparator.py`) compares local profiles; not dependent on cloud APIs.

## 9. Conflicts and contradictions

- Documented behavior vs implementation nuance:
  - In `plus.connection.getData()`, log message says `session token outdated (404)` inside `401` branch; code logic still handles `401`.
- Sync suppression asymmetry is intentional but can appear contradictory:
  - Some attributes are uploaded but never returned (one-way sync), while others are bidirectional.

## 10. Risks

- Hard endpoint coupling: backend route/shape drift breaks workflows quickly.
- Split success path: roast summary and full profile upload are decoupled; can lead to partial cloud state.
- Cache/lock dependency (`sync`, `uuid`, stock caches) can impact editability and sync continuity when corrupted/stale.
- `404` on roast fetch may delete local sync key, affecting ability to edit completed items via schedule UI.

## 11. What must not be broken

- `/aroast` upload/update contract and sync-record semantics.
- `/acoffees` fetch and schedule-linked stock update behavior.
- Deferred multipart upload path for full profile when enabled.
- `/roasts/{id}/profile/data` download and local background/template load bridge.
- References lookup with machine and fallback behavior.
- Cupping and roast-property roundtrip between UI, local profile, and cloud sync.

## 12. Owner questions

1. For current Roastlocal production, is full profile upload (`/roasts/{id}/upload-profile`) mandatory, optional, or phased?
2. Should Roastlocal guarantee backward-compatible `data.items` shape for `/roasts/references` exactly as expected by `getReferencesFromAPI()`?
3. Are one-way sync fields (uploaded but not returned) intentionally unsupported for cross-client consistency, or should backend start echoing them?
4. On roast deletion/404, is local sync-key removal the desired behavior for Roastlocal, or should soft-recovery semantics be preferred?
5. Is non-default server mode guaranteed in deployment (required for profile upload/download feature flags)?

## 13. Suggested next investigation

Narrow deep-dive on the `/aroast` and `/roasts/{id}/profile/data` contract validation against real Roastlocal responses:
- field-by-field compatibility matrix,
- optional/missing field behavior,
- error code handling (401/404/409/5xx),
- reconciliation behavior when summary upload succeeds but profile upload fails.
