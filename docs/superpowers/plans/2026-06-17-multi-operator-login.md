# Multi-operator cloud login & operator switching — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let multiple operators share one machine — save several Roastlocal Cloud logins, switch the active operator in one click (optional PIN), drive the roast operator name from the account nickname, and hide the manual operator field while logged in.

**Architecture:** A new pure module `plus/operators.py` owns the saved-operators list (JSON in QSettings) and PIN hashing. Passwords stay in the OS keyring (unchanged). `plus/controller.py` gains `switchOperator()`, `plus/connection.py` gains a `force_operator` path in `setToken`, and `artisanlib/main.py` / `roast_properties.py` wire the UI and operator-field visibility. Online-only; offline keeps the manual text operator.

**Tech Stack:** Python 3.11+, PyQt6, `keyring`, `hashlib`/`hmac`, `QSettings`, pytest.

**Spec:** `docs/superpowers/specs/2026-06-17-multi-operator-login-design.md`

**Conventions for every task:** run tests with the project venv and offscreen Qt:
`QT_QPA_PLATFORM=offscreen ./.venv-mac-arm64/bin/python -m pytest <path> -v`
(pytest may not be installed in the venv; if `No module named pytest`, run the test module directly as the existing repo tests do — import the test module and call each `test_*` function. The CI/Windows venv has pytest.)

---

## File Structure

- **Create** `src/plus/operators.py` — saved-operators list load/save (JSON in QSettings); `OperatorEntry`; find/upsert/remove; PIN hash/verify. Pure, no Qt widgets, unit-testable.
- **Modify** `src/plus/connection.py` — add `force_operator` parameter to `setToken`.
- **Modify** `src/plus/controller.py` — add `switchOperator(email)`; add-operator hook after a successful login.
- **Modify** `src/artisanlib/main.py` — settings load/save of `plus_saved_operators`; migration seed; "Operators" menu + manager dialog wiring; recompute operator-field visibility on login/logout.
- **Modify** `src/artisanlib/roast_properties.py` — hide/show the operator field per login state.
- **Create tests** `src/test/unitary/plus/test_operators.py`, `src/test/unitary/plus/test_set_token_force.py`, `src/test/unitary/plus/test_switch_operator.py`.

---

## Task 1: Operator list model + JSON persistence

**Files:**
- Create: `src/plus/operators.py`
- Test: `src/test/unitary/plus/test_operators.py`

- [ ] **Step 1: Write the failing test**

```python
# src/test/unitary/plus/test_operators.py
"""Unit tests for the saved-operators store (multi-operator cloud login)."""
import sys
from PyQt6.QtCore import QSettings, QCoreApplication
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
QCoreApplication.setOrganizationName('roastartisan-test')
QCoreApplication.setApplicationName('operators-unittest')

import plus.operators as ops  # noqa: E402


def _clear():
    QSettings().remove(ops._SETTINGS_KEY)


def test_load_empty_returns_empty_list():
    _clear()
    assert ops.load_operators() == []


def test_save_then_load_roundtrip():
    _clear()
    entries = [ops.new_entry('a@x.io', 'Иван', 'https://artisan.plus', account_id='7')]
    ops.save_operators(entries)
    loaded = ops.load_operators()
    assert len(loaded) == 1
    assert loaded[0]['email'] == 'a@x.io'
    assert loaded[0]['nickname'] == 'Иван'
    assert loaded[0]['account_id'] == '7'
    assert loaded[0]['pin_hash'] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-mac-arm64/bin/python -m pytest src/test/unitary/plus/test_operators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plus.operators'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/plus/operators.py
"""Saved-operators store for multi-operator cloud login.

Persists a list of saved Roastlocal Cloud operators (email + cached nickname + optional PIN) in
QSettings as a JSON string. Passwords are NOT stored here -- they stay in the OS keyring keyed by
email (see plus.connection / plus.config.get_keyring_service_name). PINs are stored only as
salted PBKDF2 hashes, never plaintext.
"""
import hashlib
import hmac
import json
import logging
import os
from typing import Optional, TypedDict

from PyQt6.QtCore import QSettings

_log = logging.getLogger(__name__)

_SETTINGS_KEY = 'plus_saved_operators'
_PIN_ITERATIONS = 200_000


class OperatorEntry(TypedDict):
    email: str
    nickname: str
    account_id: Optional[str]
    server_url: str
    pin_hash: Optional[str]   # hex digest, or None
    pin_salt: Optional[str]   # hex salt, or None


def new_entry(email: str, nickname: str, server_url: str,
              account_id: Optional[str] = None) -> OperatorEntry:
    return OperatorEntry(email=email, nickname=nickname, account_id=account_id,
                         server_url=server_url, pin_hash=None, pin_salt=None)


def load_operators() -> 'list[OperatorEntry]':
    raw = QSettings().value(_SETTINGS_KEY, '')
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict) and e.get('email')]
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
    return []


def save_operators(operators: 'list[OperatorEntry]') -> None:
    QSettings().setValue(_SETTINGS_KEY, json.dumps(operators))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-mac-arm64/bin/python -m pytest src/test/unitary/plus/test_operators.py -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add src/plus/operators.py src/test/unitary/plus/test_operators.py
git commit -m "feat(plus): saved-operators JSON store (load/save/new_entry)"
```

---

## Task 2: find / upsert / remove operations

**Files:**
- Modify: `src/plus/operators.py`
- Test: `src/test/unitary/plus/test_operators.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_upsert_adds_then_updates():
    entries: list = []
    entries = ops.upsert_operator(entries, 'a@x.io', 'Иван', 'https://artisan.plus', '7')
    assert len(entries) == 1
    # second upsert with same email updates nickname, does not duplicate
    entries = ops.upsert_operator(entries, 'a@x.io', 'Иван П.', 'https://artisan.plus', '7')
    assert len(entries) == 1
    assert entries[0]['nickname'] == 'Иван П.'


def test_find_and_remove():
    entries = ops.upsert_operator([], 'a@x.io', 'Иван', 'https://artisan.plus')
    entries = ops.upsert_operator(entries, 'b@x.io', 'Мария', 'https://artisan.plus')
    assert ops.find_operator(entries, 'b@x.io')['nickname'] == 'Мария'
    entries = ops.remove_operator(entries, 'a@x.io')
    assert ops.find_operator(entries, 'a@x.io') is None
    assert len(entries) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-mac-arm64/bin/python -m pytest src/test/unitary/plus/test_operators.py -k "upsert or find_and_remove" -v`
Expected: FAIL — `AttributeError: module 'plus.operators' has no attribute 'upsert_operator'`.

- [ ] **Step 3: Write minimal implementation** (append to `operators.py`)

```python
def find_operator(operators: 'list[OperatorEntry]', email: str) -> Optional[OperatorEntry]:
    for e in operators:
        if e.get('email') == email:
            return e
    return None


def upsert_operator(operators: 'list[OperatorEntry]', email: str, nickname: str,
                    server_url: str, account_id: Optional[str] = None) -> 'list[OperatorEntry]':
    entry = find_operator(operators, email)
    if entry is not None:
        entry['nickname'] = nickname
        entry['server_url'] = server_url
        if account_id is not None:
            entry['account_id'] = account_id
    else:
        operators.append(new_entry(email, nickname, server_url, account_id))
    return operators


def remove_operator(operators: 'list[OperatorEntry]', email: str) -> 'list[OperatorEntry]':
    return [e for e in operators if e.get('email') != email]
```

- [ ] **Step 4: Run test to verify it passes**

Run the `-k "upsert or find_and_remove"` command above. Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add src/plus/operators.py src/test/unitary/plus/test_operators.py
git commit -m "feat(plus): find/upsert/remove for saved operators"
```

---

## Task 3: PIN hashing and verification

**Files:**
- Modify: `src/plus/operators.py`
- Test: `src/test/unitary/plus/test_operators.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_pin_set_verify_and_clear():
    entry = ops.new_entry('a@x.io', 'Иван', 'https://artisan.plus')
    assert ops.has_pin(entry) is False
    assert ops.verify_pin(entry, '9999') is True          # no PIN set -> always allowed
    ops.set_pin(entry, '1234')
    assert ops.has_pin(entry) is True
    assert entry['pin_hash'] != '1234'                    # never stored in plaintext
    assert ops.verify_pin(entry, '1234') is True
    assert ops.verify_pin(entry, '0000') is False
    ops.clear_pin(entry)
    assert ops.has_pin(entry) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-mac-arm64/bin/python -m pytest src/test/unitary/plus/test_operators.py -k pin -v`
Expected: FAIL — `AttributeError: ... has no attribute 'set_pin'`.

- [ ] **Step 3: Write minimal implementation** (append to `operators.py`)

```python
def hash_pin(pin: str, salt: Optional[bytes] = None) -> 'tuple[str, str]':
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt, _PIN_ITERATIONS)
    return dk.hex(), salt.hex()


def has_pin(entry: OperatorEntry) -> bool:
    return bool(entry.get('pin_hash')) and bool(entry.get('pin_salt'))


def set_pin(entry: OperatorEntry, pin: str) -> None:
    h, s = hash_pin(pin)
    entry['pin_hash'] = h
    entry['pin_salt'] = s


def clear_pin(entry: OperatorEntry) -> None:
    entry['pin_hash'] = None
    entry['pin_salt'] = None


def verify_pin(entry: OperatorEntry, pin: str) -> bool:
    if not has_pin(entry):
        return True
    try:
        salt = bytes.fromhex(entry['pin_salt'])         # type: ignore[arg-type]
        dk, _ = hash_pin(pin, salt)
        return hmac.compare_digest(dk, entry['pin_hash'])   # type: ignore[arg-type]
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run the `-k pin` command above. Expected: PASS (1).

- [ ] **Step 5: Commit**

```bash
git add src/plus/operators.py src/test/unitary/plus/test_operators.py
git commit -m "feat(plus): salted PBKDF2 PIN hashing/verification for operators"
```

---

## Task 4: `setToken(force_operator=...)` — operator-name sync

**Files:**
- Modify: `src/plus/connection.py` (`setToken`, currently lines ~93-107)
- Test: `src/test/unitary/plus/test_set_token_force.py`

- [ ] **Step 1: Write the failing test**

```python
# src/test/unitary/plus/test_set_token_force.py
"""setToken must overwrite a non-empty operator only when force_operator=True."""
import sys
from unittest.mock import Mock
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
import plus.config as config        # noqa: E402
import plus.connection as connection  # noqa: E402


def _aw_with_operator(value):
    aw = Mock()
    aw.qmc = Mock()
    aw.qmc.operator = value
    aw.qmc.operator_setup = ''
    return aw


def test_set_token_does_not_clobber_when_not_forced():
    config.app_window = _aw_with_operator('Existing')
    connection.setToken('tok', nickname='Иван')
    assert config.app_window.qmc.operator == 'Existing'   # unchanged on normal login


def test_set_token_fills_empty_operator():
    config.app_window = _aw_with_operator('')
    connection.setToken('tok', nickname='Иван')
    assert config.app_window.qmc.operator == 'Иван'


def test_set_token_force_overwrites_and_sets_default():
    config.app_window = _aw_with_operator('Existing')
    connection.setToken('tok', nickname='Мария', force_operator=True)
    assert config.app_window.qmc.operator == 'Мария'
    assert config.app_window.qmc.operator_setup == 'Мария'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-mac-arm64/bin/python -m pytest src/test/unitary/plus/test_set_token_force.py -v`
Expected: FAIL — `test_set_token_force_overwrites_and_sets_default` errors with `TypeError: setToken() got an unexpected keyword argument 'force_operator'`.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `setToken` in `src/plus/connection.py` (the block currently at ~93-107):

```python
def setToken(token: str, nickname: str|None = None, force_operator: bool = False) -> None:
    try:
        token_semaphore.acquire(1)
        config.token = token
        config.nickname = nickname
        aw = config.app_window
        if (aw is not None
            and nickname is not None
            and nickname != ''
            and (force_operator or aw.qmc.operator == '')
        ):  # @UndefinedVariable
            aw.qmc.operator = nickname
            if force_operator:
                # explicit operator switch: also make it the default for new roasts
                aw.qmc.operator_setup = nickname
    finally:
        if token_semaphore.available() < 1:
            token_semaphore.release(1)
```

- [ ] **Step 4: Run test to verify it passes**

Run the command from Step 2. Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add src/plus/connection.py src/test/unitary/plus/test_set_token_force.py
git commit -m "feat(plus): setToken force_operator to sync operator name on switch"
```

---

## Task 5: `controller.switchOperator(email)`

**Files:**
- Modify: `src/plus/controller.py` (add new function near `connect`/`disconnect`)
- Test: `src/test/unitary/plus/test_switch_operator.py`

**Behaviour:** verify PIN is the caller's job (UI). `switchOperator` logs out keeping saved
passwords, points the app at the new account, authenticates silently using the keyring password,
and on success syncs the operator name from the nickname. Returns `True` on success.

- [ ] **Step 1: Write the failing test**

```python
# src/test/unitary/plus/test_switch_operator.py
"""switchOperator points the app at a saved account and authenticates silently."""
import sys
from unittest.mock import Mock
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
import plus.config as config         # noqa: E402
import plus.controller as controller   # noqa: E402
import plus.connection as connection   # noqa: E402


def test_switch_operator_sets_account_and_authenticates(monkeypatch):
    aw = Mock()
    aw.qmc = Mock(); aw.qmc.operator = 'Old'
    aw.plus_account = 'old@x.io'
    config.app_window = aw

    cleared = {}
    monkeypatch.setattr(connection, 'clearCredentials',
                        lambda remove_from_keychain=True: cleared.update(rk=remove_from_keychain))
    monkeypatch.setattr(connection, 'authentify', lambda: True)
    monkeypatch.setattr(connection, 'getNickname', lambda: 'Мария')

    ok = controller.switchOperator('maria@x.io', server_url='https://artisan.plus')

    assert ok is True
    assert cleared['rk'] is False                 # saved passwords preserved
    assert aw.plus_account == 'maria@x.io'         # pointed at new account
    assert aw.qmc.operator == 'Мария'              # operator synced from nickname (forced)


def test_switch_operator_auth_failure_returns_false(monkeypatch):
    aw = Mock(); aw.qmc = Mock(); aw.plus_account = 'old@x.io'
    config.app_window = aw
    monkeypatch.setattr(connection, 'clearCredentials', lambda remove_from_keychain=True: None)
    monkeypatch.setattr(connection, 'authentify', lambda: False)
    assert controller.switchOperator('maria@x.io', server_url='https://artisan.plus') is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-mac-arm64/bin/python -m pytest src/test/unitary/plus/test_switch_operator.py -v`
Expected: FAIL — `AttributeError: module 'plus.controller' has no attribute 'switchOperator'`.

- [ ] **Step 3: Write minimal implementation** (add to `src/plus/controller.py`)

```python
def switchOperator(email: str, server_url: str|None = None) -> bool:
    """Switch the active cloud operator to `email` using the password saved in the OS keyring.

    Logs out the current operator WITHOUT deleting any saved passwords, points the app at the new
    account, authenticates silently, and on success syncs the roast operator name from the
    account nickname. Returns True on success. PIN verification (if any) is the caller's job.
    """
    aw = config.app_window
    if aw is None:
        return False
    # log out current operator but keep everyone's saved keyring passwords
    connection.clearCredentials(remove_from_keychain=False)
    if server_url is not None:
        aw.plus_server_url = server_url
        config.server_url = server_url
    aw.plus_account = email
    aw.plus_email = email
    config.passwd = None  # force reload from keyring for the new account in authentify()
    try:
        ok = connection.authentify()
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
        ok = False
    if ok:
        connection.setToken(config.token, connection.getNickname(), force_operator=True)
    return ok
```

> Worker note: confirm `_log`, `config`, and `connection` are already imported at the top of `controller.py` (they are used throughout). `config.server_url` is the live server URL field used by `get_keyring_service_name()`.

- [ ] **Step 4: Run test to verify it passes**

Run the command from Step 2. Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add src/plus/controller.py src/test/unitary/plus/test_switch_operator.py
git commit -m "feat(plus): switchOperator() silent re-login from keyring + operator sync"
```

---

## Task 6: Remember an operator after a successful login

**Files:**
- Modify: `src/plus/controller.py` (the successful-login path inside `connect()`, around the point where `keyring.set_password(...)` runs / after auth succeeds and `aw.plus_account` + nickname are known)

**Goal:** when a login succeeds and the user kept "Remember", upsert the account into the saved
list (email + nickname + account_id + server_url) so it appears in the Operators menu.

- [ ] **Step 1: Add the upsert at the end of the successful-login path**

Locate, in `connect()`, the point after authentication has succeeded and `aw.plus_account` is set
and the nickname is available (`connection.getNickname()`), guarded by the existing
"remember credentials" condition. Add:

```python
import plus.operators as operators  # at top of controller.py with the other imports
...
# remember this operator for one-click switching later
try:
    if aw.plus_remember_credentials and aw.plus_account:
        ops_list = operators.load_operators()
        ops_list = operators.upsert_operator(
            ops_list, aw.plus_account, connection.getNickname() or aw.plus_account,
            config.server_url, account_id=aw.plus_account_id)
        operators.save_operators(ops_list)
except Exception as e:  # pylint: disable=broad-except
    _log.exception(e)
```

- [ ] **Step 2: Manual verification**

Build/run, log in with "Remember" checked, quit, restart. Confirm via a quick REPL or by reading
QSettings that `plus_saved_operators` now contains the account. (No automated test: this path
needs a live login dialog + cloud.)

- [ ] **Step 3: Commit**

```bash
git add src/plus/controller.py
git commit -m "feat(plus): remember operator in saved list after successful login"
```

---

## Task 7: Settings load/save + migration seed

**Files:**
- Modify: `src/artisanlib/main.py` (settings load near line ~18279; settings save near ~20339)

**Goal:** the saved-operators list already persists via `plus.operators` (its own QSettings key), so
no new load/save of the list is required. This task only adds the **migration seed**: if a user
upgrades with an existing remembered `plus_account` but an empty operators list, seed it.

- [ ] **Step 1: Add migration after plus settings are loaded**

In the settings-load path (right after `self.plus_account`, `self.plus_account_id`,
`self.plus_server_url` are read, ~line 18285), add:

```python
# Migration: seed the saved-operators list from a pre-existing remembered account
try:
    import plus.operators as operators
    if self.plus_account:
        _ops = operators.load_operators()
        if operators.find_operator(_ops, self.plus_account) is None:
            _ops = operators.upsert_operator(
                _ops, self.plus_account,
                (self.plus_account or ''), self.plus_server_url,
                account_id=self.plus_account_id)
            operators.save_operators(_ops)
except Exception as e:  # pylint: disable=broad-except
    _log.exception(e)
```

> The seed nickname falls back to the email; it is refreshed to the real nickname on the next
> successful login (Task 6).

- [ ] **Step 2: Manual verification**

With an existing remembered account, launch the new build once and confirm `plus_saved_operators`
gains that account (read QSettings).

- [ ] **Step 3: Commit**

```bash
git add src/artisanlib/main.py
git commit -m "feat: seed saved-operators list from existing remembered account"
```

---

## Task 8: "Operators" menu in the menu bar

**Files:**
- Modify: `src/artisanlib/main.py` (menu construction; follow the existing pattern used to build other top-level menus / the plus-related actions)

**Goal:** add a top-level (or under the existing config/plus area) **Operators** submenu that lists
saved operators (checkmark on the active `plus_account`), plus `Add operator…` and
`Manage operators…`. Rebuild its contents whenever it is about to show.

- [ ] **Step 1: Build the menu and a rebuild slot**

Add a `QMenu` (e.g. `self.operatorsMenu`) created next to the other menus. Connect its
`aboutToShow` to a `populateOperatorsMenu` slot:

```python
@pyqtSlot()
def populateOperatorsMenu(self) -> None:
    import plus.operators as operators
    self.operatorsMenu.clear()
    for entry in operators.load_operators():
        act = self.operatorsMenu.addAction(entry.get('nickname') or entry['email'])
        act.setCheckable(True)
        act.setChecked(entry['email'] == self.plus_account)
        act.triggered.connect(lambda _checked=False, e=dict(entry): self.switchToOperator(e))
    self.operatorsMenu.addSeparator()
    addAct = self.operatorsMenu.addAction(QApplication.translate('Menu', 'Add operator…'))
    addAct.triggered.connect(self.addOperator)
    mgrAct = self.operatorsMenu.addAction(QApplication.translate('Menu', 'Manage operators…'))
    mgrAct.triggered.connect(self.manageOperators)
```

- [ ] **Step 2: Implement `switchToOperator` (PIN gate + switch + UI refresh)**

```python
@pyqtSlot()
def switchToOperator(self, entry: dict) -> None:
    import plus.operators as operators
    import plus.controller as plus_controller
    from PyQt6.QtWidgets import QInputDialog, QLineEdit
    if operators.has_pin(entry):
        pin, okp = QInputDialog.getText(
            self, QApplication.translate('Message', 'Operator PIN'),
            QApplication.translate('Message', 'Enter PIN for {0}').format(entry.get('nickname') or entry['email']),
            QLineEdit.EchoMode.Password)
        if not okp or not operators.verify_pin(entry, pin):
            self.sendmessage(QApplication.translate('Message', 'Wrong PIN'))
            return
    ok = plus_controller.switchOperator(entry['email'], server_url=entry.get('server_url'))
    if not ok:
        # stored password missing/invalid -> fall back to the normal login flow
        plus_controller.connect(self)
    self.updatePlusStatusSignal.emit()   # refresh plus icon + operator-field visibility (Task 10)
```

- [ ] **Step 3: Stub `addOperator` / `manageOperators`**

```python
@pyqtSlot()
def addOperator(self) -> None:
    import plus.controller as plus_controller
    plus_controller.connect(self)        # existing login dialog; Task 6 remembers it on success
    self.updatePlusStatusSignal.emit()

@pyqtSlot()
def manageOperators(self) -> None:
    from artisanlib.operators_dialog import OperatorsDialog   # created in Task 9
    OperatorsDialog(self, self).exec()
    self.updatePlusStatusSignal.emit()
```

- [ ] **Step 4: Manual verification**

Run the app. The Operators menu lists saved operators with a checkmark on the active one; picking
another switches (prompting for PIN if set) and the operator name updates on the next roast.

- [ ] **Step 5: Commit**

```bash
git add src/artisanlib/main.py
git commit -m "feat(ui): Operators menu with one-click switch + PIN prompt"
```

---

## Task 9: "Manage operators" dialog

**Files:**
- Create: `src/artisanlib/operators_dialog.py`

**Goal:** a small dialog listing saved operators with Remove, Set PIN, Clear PIN, and Add. Follow
the existing Artisan dialog pattern (subclass of the project's `ArtisanDialog`/`QDialog` as used by
other dialogs in `artisanlib/`).

- [ ] **Step 1: Implement the dialog**

```python
# src/artisanlib/operators_dialog.py
"""Manage saved cloud operators: remove, set/clear PIN, add."""
import logging
from PyQt6.QtWidgets import (QDialog, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout,
                             QPushButton, QInputDialog, QLineEdit, QMessageBox)
from PyQt6.QtCore import QCoreApplication
import plus.operators as operators

_log = logging.getLogger(__name__)
_tr = QCoreApplication.translate


class OperatorsDialog(QDialog):
    def __init__(self, parent, aw) -> None:
        super().__init__(parent)
        self.aw = aw
        self.setWindowTitle(_tr('Form Caption', 'Manage Operators'))
        self.listw = QListWidget()
        self._reload()
        btnPin = QPushButton(_tr('Button', 'Set/Clear PIN'))
        btnPin.clicked.connect(self._toggle_pin)
        btnRemove = QPushButton(_tr('Button', 'Remove'))
        btnRemove.clicked.connect(self._remove)
        btnAdd = QPushButton(_tr('Button', 'Add'))
        btnAdd.clicked.connect(self._add)
        btnClose = QPushButton(_tr('Button', 'Close'))
        btnClose.clicked.connect(self.accept)
        row = QHBoxLayout()
        for b in (btnAdd, btnPin, btnRemove, btnClose):
            row.addWidget(b)
        lay = QVBoxLayout()
        lay.addWidget(self.listw)
        lay.addLayout(row)
        self.setLayout(lay)

    def _reload(self) -> None:
        self.listw.clear()
        for e in operators.load_operators():
            label = (e.get('nickname') or e['email'])
            if operators.has_pin(e):
                label += '  🔒'
            item = QListWidgetItem(label)
            item.setData(256, e['email'])   # Qt.ItemDataRole.UserRole == 256
            self.listw.addItem(item)

    def _selected_email(self):
        it = self.listw.currentItem()
        return None if it is None else it.data(256)

    def _toggle_pin(self) -> None:
        email = self._selected_email()
        if not email:
            return
        ops_list = operators.load_operators()
        entry = operators.find_operator(ops_list, email)
        if entry is None:
            return
        if operators.has_pin(entry):
            operators.clear_pin(entry)
        else:
            pin, ok = QInputDialog.getText(self, _tr('Message', 'Set PIN'),
                                           _tr('Message', 'New PIN (digits):'),
                                           QLineEdit.EchoMode.Password)
            if not ok or not pin:
                return
            operators.set_pin(entry, pin)
        operators.save_operators(ops_list)
        self._reload()

    def _remove(self) -> None:
        email = self._selected_email()
        if not email:
            return
        operators.save_operators(operators.remove_operator(operators.load_operators(), email))
        # offer to also delete the saved password from the keyring
        if QMessageBox.question(self, _tr('Message', 'Remove password'),
                                _tr('Message', 'Also delete the saved password for {0}?').format(email)
                                ) == QMessageBox.StandardButton.Yes:
            try:
                import keyring, plus.config as config
                keyring.delete_password(config.get_keyring_service_name(), email)
            except Exception as e:  # pylint: disable=broad-except
                _log.exception(e)
        self._reload()

    def _add(self) -> None:
        import plus.controller as plus_controller
        plus_controller.connect(self.aw)
        self._reload()
```

- [ ] **Step 2: Manual verification**

Open Operators → Manage operators…; add, set a PIN (lock icon appears), clear it, remove (with the
password-delete prompt). Confirm `plus_saved_operators` reflects each change.

- [ ] **Step 3: Commit**

```bash
git add src/artisanlib/operators_dialog.py
git commit -m "feat(ui): Manage Operators dialog (remove / set-clear PIN / add)"
```

---

## Task 10: Hide the operator field while logged in

**Files:**
- Modify: `src/artisanlib/roast_properties.py` (the operator field `lineEditOperator` + its label, populated at ~line 4630; setup default at ~4575)

**Goal:** when an operator is logged in (`self.aw.plus_account is not None`), hide the Operator
field and its label in Roast Properties; otherwise show it (free text, current behaviour).

- [ ] **Step 1: Hide/show at dialog build time**

Where the operator widgets are created/populated in the Roast Properties dialog, after setting
their text, add:

```python
_logged_in = self.aw.plus_account is not None
self.setup_ui.lineEditOperator.setVisible(not _logged_in)
# hide the paired label too (use the actual label attribute name from the .ui; e.g. labelOperator)
if hasattr(self.setup_ui, 'labelOperator'):
    self.setup_ui.labelOperator.setVisible(not _logged_in)
```

> Worker note: open the corresponding generated UI file (`src/uic/`) or the dialog code to find the
> exact label widget paired with `lineEditOperator` (commonly `labelOperator`). Hide that exact
> widget. Do not remove the widgets — only toggle visibility, so logging out restores them.

- [ ] **Step 2: Keep `qmc.operator` authoritative when logged in**

In the dialog's accept/apply path where `self.aw.qmc.operator = self.setup_ui.lineEditOperator.text()`
is set (~line 6105), guard it so a hidden field can't blank the login-driven operator:

```python
if self.aw.plus_account is None:
    self.aw.qmc.operator = self.setup_ui.lineEditOperator.text()
# when logged in, qmc.operator is driven by the active account nickname (Task 4/5) -- leave it
```

- [ ] **Step 3: Manual verification**

- Logged out: the Operator field shows and is editable; entering a name saves it on the roast.
- Logged in: the Operator field is hidden; the roast's operator equals the account nickname; after
  switching operators the new roast shows the new nickname.

- [ ] **Step 4: Commit**

```bash
git add src/artisanlib/roast_properties.py
git commit -m "feat(ui): hide roast-properties operator field while logged in to cloud"
```

---

## Self-Review

**Spec coverage:**
- Data model + JSON store → Tasks 1–2. PIN hashing → Task 3. Operator-name sync (`force`) → Task 4.
  Switch flow → Task 5. Remember-after-login → Task 6. Migration seed → Task 7. Operators menu +
  one-click switch + PIN gate → Task 8. Manage dialog (remove/PIN/add + keyring delete) → Task 9.
  Operator-field visibility → Task 10. Passwords-in-keyring (unchanged) → relied on by Tasks 5/6/9.
  All spec sections are covered.

**Placeholder scan:** Core/logic tasks (1–5) contain complete code and runnable test commands. UI
tasks (6–10) contain complete code where deterministic and explicit worker notes where an exact
existing widget/menu anchor must be located in the codebase (these are integration points, not
placeholders) with concrete manual-verification steps.

**Type consistency:** `OperatorEntry` keys (`email`, `nickname`, `account_id`, `server_url`,
`pin_hash`, `pin_salt`) are used consistently across Tasks 1–9. `new_entry`, `load_operators`,
`save_operators`, `find_operator`, `upsert_operator`, `remove_operator`, `has_pin`, `set_pin`,
`clear_pin`, `verify_pin` names match between definition (Tasks 1–3) and callers (Tasks 5–10).
`switchOperator(email, server_url=...)` signature matches its caller in Task 8. `setToken(token,
nickname, force_operator)` matches its callers in Tasks 4–5.

**Dependencies / ordering:** Tasks 1→2→3 (same module) then 4, 5 depend on 1–4. Tasks 6,7 depend on
1–2. Tasks 8,9 depend on 1–5 (and 9 is referenced by 8). Task 10 is independent of 1–9 (only reads
`plus_account`). See the execution waves in the handoff.
