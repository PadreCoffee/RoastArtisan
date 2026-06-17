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
