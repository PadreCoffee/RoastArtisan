# Multi-operator cloud login & operator switching — Design

- **Date:** 2026-06-17
- **Status:** Approved design (pending spec review)
- **Scope:** RoastArtisan (PyQt6) + Roastlocal Cloud integration (`src/plus/`)

## Problem / goal

Several operators share one computer in a roastery. Each has their own Roastlocal Cloud
account (email + password). Today only **one** account can be remembered, switching means
retyping credentials, and the operator name written on a roast is a manual free-text field.

**Goal:** save several operators' cloud credentials on one machine, switch the active operator
in **one click** (with an optional PIN), and have the roast's operator name follow the
logged-in account automatically.

## Non-goals

- No change to the cloud auth protocol or server.
- **Online-only feature.** Offline (no cloud), the operator is entered manually as free text
  exactly as today — no switching, no PINs, no stored passwords involved.
- The PIN is a soft in-app gate, **not** strong security (see Security).
- One active operator at a time (no simultaneous multi-account).

## Current state (implementation anchors)

- Login: plus toolbar → `plus.controller.connect()` → Login dialog (`plus/login.py`) → password
  stored in the **OS keyring**, keyed by `config.get_keyring_service_name()` + email
  (`plus/config.py:223`). Keyring already supports multiple emails per service.
- `plus/connection.py`:
  - `setToken(token, nickname)` sets `config.nickname` and — **only if `qmc.operator == ''`** —
    `qmc.operator = nickname` (`connection.py:93-104`).
  - `authentify()` reads the password from keyring by `aw.plus_account` (`connection.py:162-168`).
  - `clearCredentials(remove_from_keychain=False)` logs out but **keeps** the keyring entry
    (`connection.py:110-149`).
  - Cloud auth returns the account display name as `res['result']['user']['nickname']`
    (`connection.py:202`).
- Operator: `qmc.operator` (per roast) + `qmc.operator_setup` (default), edited via
  `lineEditOperator` in `roast_properties.py`, saved onto the roast.
- Active account persisted in QSettings: `plus_account`, `plus_email`, `plus_server_url`,
  `plus_account_id`, `plus_user_id`, `plus_remember_credentials` (`main.py:18279`/`20339`).

## Design

### Data model

- New QSettings key **`plus_saved_operators`** (a JSON string): a list of entries, each:
  - `email` — login and keyring key
  - `nickname` — cached cloud display name (shown in the menu; used as the operator name)
  - `account_id` — cached
  - `server_url` — needed because the keyring service name depends on it
  - `pin_hash`, `pin_salt` — optional; `null` when no PIN is set
- **Passwords stay in the OS keyring** unchanged; the list only references `email`. No plaintext
  credentials and no new secret store.
- **Migration:** on first load with this build, if `plus_account` is set and not already in the
  list, seed an entry from it (email + cached nickname) so the existing operator appears.

### Operator-name source & sync

- The operator name is the active account's **`nickname`**.
- Add a `force` path to `setToken`: on an **explicit operator switch**, set `qmc.operator` **and**
  `qmc.operator_setup` to the nickname even when non-empty. The normal startup login keeps the
  existing "only when empty" behaviour, so a manually typed name is never clobbered on launch.

### Operator field visibility (`roast_properties.py`)

- **Logged in to the cloud** (`aw.plus_account is not None`): **hide** the Operator field
  (`lineEditOperator` + its label) completely — the name is login-driven.
- **Not logged in:** show the Operator field as editable free text (current behaviour).
- Recompute when the dialog opens and on login/logout (reuse the existing plus-status update
  signal).

### Switching (online only)

New `plus.controller.switchOperator(email)`:

1. If the entry has a `pin_hash`, prompt for the PIN and verify (constant-time compare of
   hashes); abort on mismatch.
2. `connection.clearCredentials(remove_from_keychain=False)` — keep everyone's saved passwords;
   reset in-memory token / passwd / nickname / account_nr.
3. Set `aw.plus_account` / `plus_email` / `plus_server_url` from the entry; reload the password
   from keyring; authenticate **silently** (no dialog). If the stored password is missing or
   invalid, fall back to the existing Login dialog.
4. On success: `setToken(..., nickname, force=True)` → `qmc.operator` / `operator_setup` =
   nickname; refresh the cached nickname in the entry.

### UI

- New **"Operators" submenu** in the menu bar (near the existing plus/account actions):
  - list of saved operators (checkmark on the active one) → click switches;
  - **Add operator…** → existing Login dialog (Remember on); on success add/update the entry and
    offer to set an optional PIN;
  - **Manage operators…** → small dialog: list with Remove, Set/Clear PIN, Add.
- The plus toolbar button is unchanged (single-click connect/toggle).
- The Operator field in roast properties is hidden/shown per the visibility rule above.

### Security / PIN

- PIN stored as a **salted hash** (`hashlib.pbkdf2_hmac('sha256', pin, salt, iterations)`), with a
  per-entry random salt; never plaintext.
- The PIN is a **soft in-app gate against casual impersonation**, not real security: anyone logged
  into the same OS user can read the keyring regardless. This is an accepted trade-off for a
  shared, trusted roastery PC, and is online-only.

### Edge cases

- **Offline / not logged in:** operator field is free text; no switching, PINs, or passwords.
- **Changed cloud password:** silent auth fails → Login dialog → update keyring.
- **Remove operator:** offer to also delete its keyring password.
- **Account configured but cloud temporarily unreachable:** operator stays the cached nickname and
  the field stays hidden (the operator is login-driven). *[decision — see Open decisions]*

### Components / files

- **New** `plus/operators.py` — saved-operators list load/save (JSON in QSettings), PIN
  hash/verify, add/remove/update. Pure and unit-testable.
- `plus/controller.py` — `switchOperator()` orchestration; add-operator hook after a successful
  login.
- `plus/connection.py` — `setToken(force=...)` parameter.
- `artisanlib/main.py` — Operators menu + manager dialog wiring; settings load/save of the list;
  migration seed; recompute operator-field visibility on login/logout.
- `artisanlib/roast_properties.py` — hide/show the operator field per login state.

### Testing

- `operators.py`: PIN hash ≠ plaintext; correct PIN verifies, wrong PIN fails; list
  add/remove/update round-trip through JSON.
- Switch logic: selecting an email sets `plus_account` and authenticates; on success
  `qmc.operator` = nickname (keyring/auth mocked); `force` overwrites a non-empty operator.
- Operator-field visibility: hidden when `plus_account` set, shown when `None`.
- Cloud auth itself is mocked.

## Open decisions (confirm during review)

1. Operator-field condition = "logged in (`plus_account` set)" vs "actively connected to the
   cloud right now". Proposed: **logged-in** (avoids the field flickering with connectivity).
2. Operators entry point = a **menu-bar submenu** (vs a dropdown on the plus toolbar button).
   Proposed: menu-bar submenu (leaves the plus button's single-click behaviour intact).
