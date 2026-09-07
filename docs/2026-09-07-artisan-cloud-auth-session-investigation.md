# Artisan Client — Cloud Auth & Session Investigation

**Date:** 2026-09-07  
**Scope:** Read-only audit of `src/plus/` — no code changed.  
**Purpose:** Confirm whether the Artisan desktop client calls `/api/v1/auth/refresh` or otherwise depends on the cloud's org-resolution-in-refresh code path, so the cloud team can assess whether a planned fix to that path is safe to ship without a client-side regression test.

---

## Evidence base

All file:line references are in `src/plus/`.

| File | Role |
|------|------|
| `config.py` | URL constants, runtime auth state |
| `connection.py` | HTTP transport: `authentify()`, `sendData()`, `getData()`, `sendFile()`, `getHeaders()` |
| `controller.py` | Connect/disconnect lifecycle, operator switching |
| `login.py` | Login dialog (UI only) |

---

## 1. Login endpoint

**Which endpoint is called?**

`config.py:210`:
```python
auth_url = api_base_url + '/accounts/users/authenticate'
```
This resolves to `https://roastlocal.ru/api/v1/accounts/users/authenticate`.

**How it is called:**

`connection.py:182–186` (`authentify()`):
```python
data = {
    'email': aw.plus_account,
    'password': config.passwd,
}
r = sendData(config.auth_url, data, 'POST', False)
```

`authorized=False` means the `Authorization` header is **not** sent for this call — it's a raw credential exchange, not a bearer-guarded request.

**Verdict:** Confirmed. The client calls exactly `POST /api/v1/accounts/users/authenticate` with `{ "email": ..., "password": ... }`.

---

## 2. Token handling

**What the server returns:**

`connection.py:196–200` — the response is expected to be JSON of the form:
```json
{
  "success": true,
  "result": {
    "user": {
      "token": "<session-token>",
      "nickname": "...",
      ...
    }
  }
}
```

**Where the token is stored:**

`connection.py:285`:
```python
setToken(res['result']['user']['token'], nickname)
```

`connection.py:93–110` (`setToken`):
```python
config.token = token        # stored in memory only
config.nickname = nickname  # in memory only
```

The token is kept only in process memory (`config.token`). The **password** (not the token) is stored in the OS keyring (`controller.py:211–213`):
```python
keyring.set_password(config.get_keyring_service_name(), login, passwd)
```

**How the token is attached to subsequent requests:**

`connection.py:349–352` (`getHeaders()`):
```python
if authorized:
    token = getToken()
    if token is not None:
        headers['Authorization'] = f'Bearer {token}'
```

Every authenticated request carries `Authorization: Bearer <token>`.

---

## 3. Refresh: does the client ever call `/auth/refresh`?

**No.**

A full-codebase search for `auth/refresh` and `refresh_token` across `src/` returned zero results.

The client's only session-renewal mechanism is a full **re-authentication**: when any request receives HTTP 401, the client calls `authentify()` again — which POSTs to `/accounts/users/authenticate` with the stored credentials to obtain a new session token.

`connection.py:407–433` (`sendData`, 401 path):
```python
if authorized and r.status_code == 401:  # authorisation failed
    _log.debug('-> session token outdated (401)')
    # we re-authentify by renewing the session token and try again
    if authentify():
        time.sleep(0.3)
        headers, postdata = getHeadersAndData(...)  # recreate header with new token
        r = requests.post(url, ...)   # retry
```

Identical pattern in `getData()` (`connection.py:496–513`) and `sendFile()` (`connection.py:464–471`).

`authentify()` always calls `POST /accounts/users/authenticate` — there is no `/auth/refresh` call anywhere.

---

## 4. On 401 / auth failure

**Silent re-authentication path (network request failed with 401):**

1. `sendData` / `getData` / `sendFile` receives 401.
2. Calls `authentify()` which re-POSTs to `/accounts/users/authenticate`.
3. On success: new token stored, original request retried once. No user interaction.
4. On failure (wrong creds / network error / subscription expired): `clearCredentials()` wipes `config.token`, `config.passwd`, `config.nickname` from memory (`connection.py:113–152`); `aw.plus_account` is also cleared.

**Does the user ever see a "logged out" state?**

Only in the interactive connect flow (`controller.py:291–299`):
```python
elif interactive:
    message = QApplication.translate('Plus', 'Authentication failed')
    aw.sendmessageSignal.emit(message, True, None)
```
This is a status-bar message, not a modal dialog. If the 401 comes from a background sync request (non-interactive), the client silently attempts re-auth; if it fails it goes dark (disconnected icon, `config.connected = False`) with no popup. The user is **never** kicked to a "you are logged out" screen the way a browser SPA is.

---

## 5. Org — does the client touch it in auth?

**No.**

The only `org`-like grep hits in `src/plus/` are in filename-extension comments (`.db.org`) inside `sync.py:82`, `register.py:67`, `account.py:83` — none related to auth.

The auth payload is strictly `{ "email": ..., "password": ... }` (`connection.py:182–185`). No `org`, `organization`, or tenant field is sent to or read from any auth-related endpoint. The client does not store or pass an org identifier anywhere in its HTTP requests.

---

## 6. Token lifetime — proactive refresh or reactive?

**Purely reactive.**

There is no timer, no background thread, and no scheduled call that proactively refreshes the token before it expires. The client does not inspect any `expires_at` or `exp` field from the login response. Session renewal happens **only** when the server returns 401 on a real request.

---

## VERDICT

| Question | Answer |
|----------|--------|
| Does the client call `POST /api/v1/auth/refresh`? | **NO** — endpoint not referenced anywhere in the codebase. |
| Does the client call any token-refresh endpoint? | **NO** — only `POST /api/v1/accounts/users/authenticate`. |
| Does the client touch `org` in the auth flow? | **NO** — payload is `{email, password}` only; no org field anywhere. |
| Does the client proactively refresh tokens? | **NO** — purely reactive: re-authenticates on 401. |
| Is the cloud `/auth/refresh` org-fix safe for the client? | **YES — the client is entirely unaffected.** |

The cloud team can ship the fix to `POST /api/v1/auth/refresh` org-resolution without any client change and without needing a real-client regression run for this specific code path. The Artisan desktop client never calls `/auth/refresh`; it re-authenticates from scratch via `/accounts/users/authenticate` each time its session token is rejected.

---

## Краткое резюме для владельца (Russian)

Клиент RoastArtisan **никогда не обращается** к эндпоинту `/api/v1/auth/refresh`. При входе в систему он делает один `POST /api/v1/accounts/users/authenticate` с email и паролем, получает сессионный токен и хранит его только в памяти. Когда токен истекает (сервер отвечает 401), клиент молча повторяет вход с сохранёнными в связке ключей ОС учётными данными — никаких popup, никакого «выкидывания» пользователя, как в браузере.

Поле `org` / организация клиентом **нигде не передаётся и не хранится** в контексте авторизации.

Следовательно, облачный фикс, который меняет логику определения организации внутри `/auth/refresh`, **абсолютно безопасен для клиента без каких-либо изменений на клиентской стороне**. Дополнительный регрессионный прогон с реальным клиентом для этого конкретного изменения не требуется.
