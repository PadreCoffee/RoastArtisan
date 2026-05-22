# Client Investigation: Roastlocal Cloud Access, Authentication, and Session State

## 1. Research question
How does the modified Artisan client configure Roastlocal Cloud access, authentication, and session state?

## 2. Executive summary
The Plus integration is configured around a persisted server base URL (`plus_server_url`) that is normalized and used to derive both web and API base URLs. By default it points to `https://artisan.plus`, but the UI allows runtime override (including local HTTP for localhost).

Authentication is email/password based via `POST /api/v1/accounts/users/authenticate`. Passwords are intended to be persisted in OS keyring when "Remember" is enabled; the session token itself is kept in memory only (`config.token`) and injected as `Authorization: Bearer ...`.

Session identity state is persisted partly in `QSettings` (`plus_account`, `plus_email`, `plus_user_id`, `plus_account_id`, `plus_server_url`) and partly in runtime memory (`token`, `passwd`, `nickname`). On `401`, transport automatically re-authenticates once and retries.

No cookie-based session mechanism is implemented in client transport code. Multi-tenant/account scoping appears account-centric (`plus_account_id`) with store/location selection (`plus_store`, `plus_default_store`) rather than explicit tenant selection UI.

## 3. Files inspected
- `src/plus/config.py`
- `src/plus/controller.py`
- `src/plus/connection.py`
- `src/plus/login.py`
- `src/plus/stock.py`
- `src/plus/sync.py`
- `src/plus/queue.py`
- `src/plus/account.py`
- `src/plus/roast.py`
- `src/plus/util.py`
- `src/artisanlib/main.py`
- `src/artisanlib/util.py`
- `src/test/unitary/plus/test_config.py`
- `src/test/unitary/plus/test_connection.py`
- `docs/recovery/client-investigations/03_http_network_layer.md`
- `docs/recovery/client-investigations/06_ui_actions_cloud_calls.md`

## 4. Facts from code
### 4.1 Base URL and endpoint construction
- Defaults are hardcoded in `plus.config`:
  - `default_web_base_url = https://artisan.plus`
  - `default_api_base_url = https://artisan.plus/api/v1`
  - `default_shop_base_url = https://buy.artisan.plus/`
- `set_server_base_url()` derives all service endpoints from one server URL (`web_base_url`, `api_base_url`, auth, stock, roast, notifications, schedule lock, profile upload/fetch URLs).
- `derive_service_base_urls()` appends `/api/v1` unless already present, and supports both root URLs and URLs already ending in `/api/v1`.
- `normalize_server_url()` auto-adds scheme:
  - `http://` for localhost/127.0.0.1/::1
  - `https://` for other hosts

### 4.2 Persisted configuration and session-related settings
- In `ApplicationWindow` state (`artisanlib/main.py`):
  - `plus_account`, `plus_email`, `plus_remember_credentials`, `plus_server_url`, `plus_language`, `plus_user_id`, `plus_account_id` are loaded from `QSettings`.
  - Same fields are written back to `QSettings` during save.
- `plus_account`/`plus_server_url` are only loaded from default app settings (not external settings export import).
- `plus_server_url` is applied at settings load via `plus.config.set_server_base_url(self.plus_server_url)`.

### 4.3 Credential and token storage
- Password:
  - Stored/retrieved through `keyring.set_password/get_password` using service name `artisan.plus` or `artisan.plus@<server_url>` for non-default server.
  - If remember is disabled, email may be cleared and password stays only in process memory for the session (`config.passwd`).
- Token:
  - Stored only in runtime memory (`config.token`), protected by `token_semaphore` accessors.
  - Cleared in `clearCredentials()`.
- Other persisted identity:
  - `plus_user_id` and `plus_account_id` are persisted in `QSettings`.

### 4.4 Login/auth flow
- Connect path (`plus.controller.connect()`):
  1. Apply `plus_server_url` to endpoint config.
  2. Try keyring password lookup for account.
  3. If interactive and needed, show login dialog (`plus.login.plus_login`) with fields: Server URL, Email, Password, Remember.
  4. Persist selected account/server/remember/email state in app settings objects.
  5. Authenticate via `plus.connection.authentify()`.
- `authentify()` sends JSON `{ email, password }` to `/accounts/users/authenticate`.
- On success, client expects nested contract fields including `result.user.token`; then sets:
  - bearer token and nickname
  - `plus_user_id`, `plus_account_id`, `plus_language`, readonly flag
  - subscription/limit data (if present)

### 4.5 Session persistence and re-auth behavior
- Session token is not persisted across app restart; re-login depends on stored keyring password + remembered account/email.
- For authorized `GET/POST/PUT/file-upload`, if response is `401`, client performs one re-authentication and retries request.
- Connection state (`config.connected`) can be false while Plus is still ON (`plus_account` exists), enabling reconnect behavior.

### 4.6 Headers, cookies, and transport
- Request headers include:
  - `User-Agent: Artisan/<version> (<os; version; arch>)`
  - `Accept-Charset: utf-8`
  - `Accept-Language` from app locale (if available)
  - `Authorization: Bearer <token>` when authorized
  - `Accept-Encoding` for compressed responses
  - `Content-Type: application/json; charset=utf-8` for JSON write calls
  - `Idempotency-Key` on POST
- Client can gzip JSON payloads above configured threshold.
- No cookie jar handling, no explicit cookie headers, no session-cookie flow in Plus transport code.

### 4.7 Organization/tenant selection and operator/user identity
- Explicit tenant selector was not found in auth/config flow.
- Account scope is represented by backend `account._id` mapped to `plus_account_id`.
- Store/location scope exists in scheduler/stock paths (`plus_store`, `plus_default_store`, stock `location_hr_id`).
- User identity:
  - login email (`plus_account`)
  - backend user UUID (`plus_user_id`)
  - optional nickname from auth response (also used to prefill `qmc.operator` when empty)

### 4.8 What appears hardcoded
- Default cloud domains and major endpoint suffixes are hardcoded in `plus.config`.
- Auth path `accounts/users/authenticate` and multiple API resource paths are hardcoded as string composition from base URLs.
- UI status messages still brand around artisan.plus even when custom server URL is used.

## 5. Network/API behavior
| Area | Method | Path pattern | Auth | Client behavior |
|---|---|---|---|---|
| Login | POST | `/api/v1/accounts/users/authenticate` | No bearer required for initial login | Sends email/password JSON; expects `result.user.token` |
| Stock/schedule fetch | GET | `/api/v1/acoffees` | Bearer | Sends `today` and optional `lsrt` params |
| Roast sync | POST/PUT | `/api/v1/aroast` | Bearer | Uses queue/background sync; retry with re-auth on 401 |
| Notifications | GET | `/api/v1/notifications` | Bearer | Background polling path |
| Schedule lock | POST | `/api/v1/aschedule/lock` | Bearer | Queue-based action |
| Profile upload (conditional mode) | POST multipart | `/api/v1/roasts/{roast_id}/upload-profile` | Bearer | Enabled in non-default-server mode |

Notes:
- `verify_ssl = True` by default.
- Connect timeout/read timeout are fixed defaults with dynamic read-timeout increase on timeout.

## 6. Data model mapping
- Login credentials model:
  - Input: `email`, `password`, `server_url`, `remember`
  - Persisted: `plus_account`, `plus_email`, `plus_server_url`, `plus_remember_credentials`
- Auth response mapping:
  - `result.user.token` -> runtime `config.token`
  - `result.user.nickname` -> runtime `config.nickname` (+ optional `qmc.operator` fill)
  - `result.user.user_id` -> `plus_user_id`
  - `result.user.account._id` -> `plus_account_id`
  - `result.user.language` -> `plus_language`
  - `result.user.readonly` -> `plus_readonly`
- Account scoping:
  - `plus_account_id` -> local account number (`config.account_nr`) via `plus.account.setAccount()`
- Store/location scoping:
  - `location`/`location_hr_id` from stock/schedule -> `plus_store` context for roast/schedule operations

## 7. Roastlocal Cloud assumptions
Facts:
- Client assumes backend compatibility with artisan.plus-style auth and API route layout (`/api/v1/...`, nested `result.user.token`).
- Client supports changing server host at runtime and deriving endpoints from it.

Inference:
- Roastlocal Cloud integration likely relies on an adapter/compatibility contract preserving artisan.plus response shape and endpoint semantics.

## 8. Artisan compatibility assumptions
- Authentication success requires specific response nesting and key names, especially `result.user.token`.
- Scheduler and filtering logic assume stable `plus_user_id`, `plus_account_id`, store/location IDs.
- Background queue behavior assumes bearer-token renewal by re-auth with stored credentials.

## 9. Conflicts and contradictions
- Branding vs target backend:
  - Code supports custom backend URL, but user-facing text still says "artisan.plus" in many paths.
- Session persistence semantics:
  - Account/identity settings persist across restart, but bearer token does not; effective auto-login depends on keyring availability.
- Minor logging inconsistency:
  - `getData()` handles HTTP `401` but debug log message says "(404)" in one branch (message text mismatch, behavior still tied to `401`).

## 10. Risks
1. Contract fragility risk: strict dependence on nested auth response keys can break login if Roastlocal response shape changes.
2. Keyring dependency risk: if OS keyring fails/unavailable, remembered credentials flow degrades and reconnect depends on manual entry.
3. Identity persistence risk: `plus_user_id` / `plus_account_id` are persisted and may be stale until next successful auth refresh.
4. Mixed-protocol risk: localhost server URLs are forced to HTTP, non-localhost to HTTPS; misclassification or proxy setups could cause unexpected protocol behavior.
5. Sensitive metadata-at-rest risk: while token/password are not saved in QSettings, account/email/server URL and IDs are persisted.

## 11. What must not be broken
- Custom server URL normalization and endpoint derivation from one base URL.
- `/accounts/users/authenticate` response contract handling (`result.user.token`, account/user metadata).
- Keyring service-name scoping by server URL for multi-backend credential separation.
- Automatic 401 re-auth + retry behavior in `GET/POST/PUT/sendFile` transport paths.
- Persistence of `plus_account`, `plus_server_url`, `plus_email`, `plus_user_id`, `plus_account_id` in default settings.
- Store/location context propagation (`plus_store` / `location_hr_id`) in scheduler/roast flows.

## 12. Owner questions
1. Should Roastlocal Cloud guarantee full backward-compatible auth response shape (`result.user.token`, `result.user.account._id`, etc.), or can client contract be versioned?
2. Is persistent storage of `plus_user_id` and `plus_account_id` in local settings acceptable for your security posture?
3. Should local non-production URLs be allowed beyond localhost over HTTP, or is HTTPS-only desired for all environments?
4. Do you want the UI branding/messages to be backend-neutral (not artisan.plus-specific) when custom server URL is configured?
5. Is there any planned tenant/org model beyond account+store that must be surfaced in this client now?

## 13. Suggested next investigation
Perform investigation 08 focused narrowly on keyring and local settings artifacts in real runtime environments (macOS/Windows/Linux): verify exact on-disk/OS-secret-store locations, fallback behavior when keyring is unavailable, and potential forensic exposure of account identifiers (without extracting any secrets).
