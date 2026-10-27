"""R1: a transient/ambiguous authentication reply must never delete the saved password.

Before: a non-JSON reply (nginx 502/503 HTML page), a reply without content-type, an SSL error or any
unexpected exception called clearCredentials(), which deleted the password from the keychain and set
plus_account=None — one cloud restart silently logged the roaster out and roasts stopped reaching the cloud.
Now only a definitive rejection (JSON success:false = wrong login/password) clears credentials; anything
ambiguous raises a connection error, so callers keep the account ON and retry (like a timeout).
"""

import sys
from typing import Any
import types

import pytest
import requests
from PyQt6.QtWidgets import QApplication

try:  # another test module may have replaced QApplication with a mock in sys.modules
    _app: object = QApplication.instance() or QApplication(sys.argv)
except Exception:  # pylint: disable=broad-except
    _app = None

import artisanlib.main  # noqa: E402,F401

from plus import config  # noqa: E402
from plus import connection  # noqa: E402


class _Resp:
    def __init__(self, status: int, headers: dict[str, str], body=None) -> None:
        self.status_code = status
        self.headers = headers
        self._body = body

    def json(self):
        return self._body


@pytest.fixture
def env(monkeypatch):
    deleted: list[Any] = []
    import keyring
    monkeypatch.setattr(keyring, 'delete_password', lambda *a: deleted.append(a))
    monkeypatch.setattr(keyring, 'get_password', lambda *a: 'secret')
    aw = types.SimpleNamespace(plus_account='roaster@example.com', sendmessage=lambda *a, **k: None)
    monkeypatch.setattr(config, 'app_window', aw)
    monkeypatch.setattr(config, 'passwd', 'secret')
    return aw, deleted


def _reply(monkeypatch, resp=None, exc=None):
    def fake(*a, **k):
        if exc is not None:
            raise exc
        return resp
    monkeypatch.setattr(connection, 'sendData', fake)


@pytest.mark.parametrize('resp', [
    _Resp(502, {'content-type': 'text/html'}),          # nginx error page during a deploy
    _Resp(503, {'content-type': 'text/html; charset=utf-8'}),
    _Resp(204, {'content-type': 'application/json'}),
    _Resp(200, {}),                                     # no content-type header at all
])
def test_ambiguous_reply_keeps_credentials(env, monkeypatch, resp) -> None:
    aw, deleted = env
    _reply(monkeypatch, resp)
    with pytest.raises(requests.exceptions.ConnectionError):
        connection.authentify()
    assert deleted == [] and aw.plus_account == 'roaster@example.com'


@pytest.mark.parametrize('exc', [requests.exceptions.SSLError('cert'), RuntimeError('boom')])
def test_ssl_and_unexpected_errors_keep_credentials(env, monkeypatch, exc) -> None:
    aw, deleted = env
    _reply(monkeypatch, exc=exc)
    with pytest.raises(Exception):  # noqa: B017
        connection.authentify()
    assert deleted == [] and aw.plus_account == 'roaster@example.com'


def test_definitive_rejection_still_clears(env, monkeypatch) -> None:
    aw, deleted = env
    _reply(monkeypatch, _Resp(401, {'content-type': 'application/json'}, {'success': False, 'error': 'wrong password'}))
    assert connection.authentify() is False
    # removed under the current keyring name and the legacy one 1.0.14/1.0.15 used
    assert {d[1] for d in deleted} == {'roaster@example.com'} and aw.plus_account is None
    assert (config.get_keyring_service_name(), 'roaster@example.com') in deleted


def test_keychain_read_failure_does_not_delete_the_entry(env, monkeypatch) -> None:
    aw, deleted = env
    import keyring
    monkeypatch.setattr(config, 'passwd', None)
    def boom(*a):
        raise RuntimeError('keychain locked')
    monkeypatch.setattr(keyring, 'get_password', boom)
    assert connection.authentify() is False
    assert deleted == []
