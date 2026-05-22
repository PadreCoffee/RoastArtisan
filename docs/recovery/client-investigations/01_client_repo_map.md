# Client Investigation: Current structure of the modified Artisan client repository

## 1. Research question

What is the current structure of the modified Artisan client repository, with emphasis on entry points, Roastlocal Cloud integration modules, configuration, networking/API layer, cloud-related UI, import/export, profile/roast/batch handling, tests/fixtures, and docs?

## 2. Executive summary

The repository is organized around a classic Artisan desktop client core under `src/artisanlib/`, with the executable entry script in `src/artisan.py` and a substantial Roastlocal/Artisan Plus integration layer under `src/plus/`.

The cloud integration is not isolated in one file: it is split into authentication/connection (`plus/connection.py`, `plus/controller.py`), data sync/cache queueing (`plus/sync.py`, `plus/queue.py`, `plus/register.py`), domain mapping (`plus/roast.py`, `plus/stock.py`, `plus/blend.py`, `plus/weight.py`), and cloud UI/account workflows (`plus/login.py`, `plus/schedule.py`, `plus/notifications.py`).

Configuration supports both default SaaS (`https://artisan.plus`) and custom compatible backends via persisted server URL (`plus_server_url`) and dynamic endpoint derivation in `src/plus/config.py`.

Import/export and roast profile compatibility are spread across core modules (`src/artisanlib/roastlog.py`, `src/artisanlib/batches.py`, `src/artisanlib/roastpath.py`, dedicated device adapters) and backed by extensive multi-format fixture datasets in `src/test/sanity/data/`.

## 3. Files inspected

- Entry/runtime
  - `src/artisan.py`
  - `src/artisanlib/main.py`
- Cloud integration package
  - `src/plus/__init__.py`
  - `src/plus/config.py`
  - `src/plus/controller.py`
  - `src/plus/connection.py`
  - `src/plus/sync.py`
  - `src/plus/queue.py`
  - `src/plus/roast.py`
  - `src/plus/stock.py`
  - `src/plus/schedule.py`
  - `src/plus/login.py`
  - `src/plus/register.py`
  - `src/plus/notifications.py`
  - `src/plus/blend.py`
  - `src/plus/weight.py`
  - `src/plus/account.py`
  - `src/plus/util.py`
  - `src/plus/countries.py`
- Core profile/import-export related
  - `src/artisanlib/roastlog.py`
  - `src/artisanlib/batches.py`
  - `src/artisanlib/roast_properties.py`
  - `src/artisanlib/roastpath.py`
  - `src/artisanlib/cup_profile.py`
- Config/build/packaging
  - `src/pyproject.toml`
  - `src/requirements.txt`
  - `src/requirements-dev.txt`
  - `src/qt.conf`
  - `src/qt-win.conf`
  - `src/includes/logging.yaml`
  - `src/artisan-*.spec` family and platform build scripts
- Tests/fixtures/docs
  - `src/test/unitary/**`
  - `src/test/sanity/**`
  - `src/test/smoke/**`
  - `src/test/uat/**`
  - `docs/**`, `doc/**`, `wiki/**`, `README.md`

## 4. Facts from code

- Main app start path:
  - `src/artisan.py` sets runtime env vars (`OMP_NUM_THREADS`, `OPENPYXL_DEFUSEDXML`) and calls `artisanlib.main.main()` when `command_utility.handleCommands()` allows full app start.
- Main application object and cloud wiring:
  - `src/artisanlib/main.py` defines `class Artisan(QtSingleApplication)` and central `ApplicationWindow` state.
  - `src/artisanlib/main.py` imports all `plus.*` modules explicitly (`plus.config`, `plus.sync`, `plus.controller`, etc.), confirming deep integration into runtime.
- Persistent cloud-related app state in `ApplicationWindow` includes:
  - `plus_account`, `plus_account_id`, `plus_user_id`, `plus_server_url`, `plus_subscription`, `plus_paidUntil`, `plus_rlimit`, `plus_used`, `plus_readonly`.
- Plus icon/UX states in main UI are wired to sync/connection statuses:
  - icon variants include connected/unsynced/dirty/on/off variants (`plus-connected`, `plus-unsynced`, `plus-dirty`, etc.) with matching tooltips.
- Cloud sync trigger logic exists in lifecycle/background handling:
  - when app returns from background, code may refresh sync data and schedule/stock data based on state and time windows.

## 5. Network/API behavior

- Endpoint base management is centralized in `src/plus/config.py`:
  - Defaults: `default_web_base_url=https://artisan.plus`, `default_api_base_url=https://artisan.plus/api/v1`.
  - Supports custom server via URL normalization and derived `web` + `api/v1` paths.
- Concrete endpoints are assembled in `set_server_base_url()`:
  - `/accounts/users/authenticate`
  - `/acoffees`
  - `/aroast`
  - `/aschedule/lock`
  - `/notifications`
  - `/roasts/{roast_id}/upload-profile`
  - `/roasts/{roast_id}/profile/data`
  - `/roasts/references`
- Authentication flow in `src/plus/connection.py`:
  - Uses `requests` and keyring-backed credentials.
  - Stores/retrieves token and user/account metadata.
  - Handles subscription/limit/read-only metadata from server response.
- Connection orchestration in `src/plus/controller.py`:
  - `connect()`, `disconnect()`, `toggle()`, sync-on-connect behavior.
  - Supports interactive login dialog path (`plus.login.plus_login`) and non-interactive reconnect paths.

## 6. Data model mapping

- Roast/profile-to-cloud mapping is explicit in `src/plus/roast.py`:
  - Builds server roast payload from local profile dictionary (`getTemplate`).
  - Maps UUID/schedule fields:
    - local `roastUUID` -> server `id`
    - local `scheduleID` -> server `s_item_id`
    - local `scheduleDate` -> server `s_item_date`
  - Converts units (notably weights to kg) and serializes roast metrics/events.
- Sync state and identity registers are local-cache based in `src/plus/config.py` and `src/plus/sync.py`:
  - caches include `sync`, `outbox`, `uuids`, `account`, stock/schedule-related caches.
  - `sync.py` uses lock files + `shelve` + `portalocker` for shared cache coordination.
- `src/plus/register.py` (by usage from main/sync paths) functions as UUID <-> local file path registry for linked profiles.

## 7. Roastlocal Cloud assumptions

Facts:
- Client assumes a Plus-compatible HTTP API contract (authentication, roast endpoints, stock/schedule/notifications semantics).
- Client supports non-default server URL (`plus_server_url`) and derives all API routes from it.
- Non-default server enables remote profile upload/fetch flags (`profile_upload_enabled()`, `remote_profile_fetch_enabled()`).

Inference (explicit):
- The modified client is designed as an adaptation bridge where Roastlocal Cloud can act as a compatible backend if it exposes the expected Plus-like routes and payloads.

## 8. Artisan compatibility assumptions

- Core Artisan runtime remains primary (`src/artisanlib/main.py` is still monolithic central app).
- Plus/Cloud logic is additive and state-driven (account present -> plus features on), not replacing base roast logging flow.
- Many import/export/device adapters remain in `artisanlib` and are covered by tests and fixtures, indicating compatibility is preserved across machine ecosystems and file formats.

## 9. Conflicts and contradictions

- Naming mismatch (fact): many modules still describe themselves as connecting to "artisan.plus" while repository/usage context is Roastlocal-integrated.
- Endpoint contract coupling (fact): cloud-facing paths are hardcoded shape-wise in `plus/config.py`, so backend compatibility depends on preserving these routes/response structures.
- No direct contradiction found between inspected code and top-level docs on repository purpose; rather, there is dual-brand terminology (Artisan Plus naming + Roastlocal operational context).

## 10. Risks

- Tight API contract coupling risk: backend route or payload drift can break auth/sync/stock/schedule flows.
- Shared cache/lock complexity risk: corruption or stale locks in `sync`/`register`/`outbox` files can affect data consistency.
- UI state coupling risk: plus icon and user workflows depend on nuanced connected/synced/on/off states, prone to regressions if integration layer changes.
- Credential/keyring behavior risk across OS variants (Linux/macOS/Windows differences are handled but fragile).

## 11. What must not be broken

- Startup path: `src/artisan.py` -> `artisanlib.main.main()` and command-mode behavior.
- Plus-compatible authentication and token lifecycle.
- Roast UUID registration + sync cache logic that links local profiles to cloud records.
- Import/export compatibility for Artisan `.alog/.json/.csv` and external ecosystem fixtures (Cropster, Ikawa, Loring, Stronghold, etc.) represented in test data.
- Scheduler/stock/notification interactions in `plus.schedule`, `plus.stock`, `plus.notifications`.

## 12. Owner questions

- Which specific Roastlocal Cloud environments are considered first-class targets (prod/staging/local), and are all required to implement every Plus endpoint currently used?
- Is the long-term expectation to keep URL-level Plus compatibility (`/api/v1/...`) or introduce a dedicated Roastlocal contract with a translation layer?
- For profile upload/fetch behavior currently gated by non-default server URL, should Roastlocal deployment always run in "custom server" mode?
- Are there known intentionally unsupported Plus features (if any) that should be documented to avoid accidental reintroduction?

## 13. Suggested next investigation

Narrow scope next step: perform Investigation 02 focused only on HTTP contract mapping.

- Build endpoint-by-endpoint contract table from `plus/connection.py`, `plus/stock.py`, `plus/schedule.py`, `plus/sync.py`, `plus/notifications.py`.
- For each route, capture required request fields, expected response shape, and client-side fallback/error behavior.
- Identify which fields are mandatory vs optional from actual parser logic.
