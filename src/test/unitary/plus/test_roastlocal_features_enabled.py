"""1.0.14 made roastlocal.ru the default cloud address. Three things compared the server against that default,
meaning "not the upstream artisan.plus": cloud reference profiles and full profile uploads silently turned off,
and the keyring service name changed so saved passwords were not found. They now compare against the upstream."""

import sys
from typing import Any

import pytest
from PyQt6.QtWidgets import QApplication

try:  # another test module may have replaced QApplication with a mock in sys.modules
    _app: object = QApplication.instance() or QApplication(sys.argv)
except Exception:  # pylint: disable=broad-except
    _app = None

import artisanlib.main  # noqa: E402,F401
from plus import config, connection  # noqa: E402


@pytest.fixture
def roastlocal(monkeypatch:pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, 'server_url', config.normalize_server_url('roastlocal.ru'))


def test_references_and_profile_upload_are_on_for_roastlocal(roastlocal:None) -> None:
    del roastlocal
    assert config.server_url == 'https://roastlocal.ru'
    assert config.remote_profile_fetch_enabled()
    assert config.profile_upload_enabled()


def test_they_stay_off_for_the_upstream_cloud(monkeypatch:pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, 'server_url', 'https://artisan.plus')
    assert not config.remote_profile_fetch_enabled() and not config.profile_upload_enabled()
    assert config.get_keyring_service_name() == config.app_name and config.legacy_keyring_service_names() == []


def test_keyring_name_for_roastlocal_is_the_one_used_up_to_1_0_13(roastlocal:None) -> None:
    del roastlocal
    assert config.get_keyring_service_name() == 'artisan.plus@https://roastlocal.ru'
    assert config.legacy_keyring_service_names() == ['artisan.plus']


class _Keyring:
    def __init__(self, store:dict[tuple[str, str], str]) -> None:
        self.store = store

    def get_password(self, service:str, account:str) -> str|None:
        return self.store.get((service, account))

    def set_password(self, service:str, account:str, passwd:str) -> None:
        self.store[(service, account)] = passwd

    def delete_password(self, service:str, account:str) -> None:
        if (service, account) not in self.store:
            raise KeyError(service)
        del self.store[(service, account)]


@pytest.fixture
def kr(monkeypatch:pytest.MonkeyPatch) -> _Keyring:
    import keyring
    k = _Keyring({})
    for name in ('get_password', 'set_password', 'delete_password'):
        monkeypatch.setattr(keyring, name, getattr(k, name))
    return k


def test_password_saved_by_1_0_14_is_found_and_moved(roastlocal:None, kr:_Keyring) -> None:
    del roastlocal
    kr.store[('artisan.plus', 'igor@example.com')] = 'pw'
    assert connection.read_saved_password('igor@example.com') == 'pw'
    assert kr.store[('artisan.plus@https://roastlocal.ru', 'igor@example.com')] == 'pw'


def test_current_name_wins(roastlocal:None, kr:_Keyring) -> None:
    del roastlocal
    kr.store[('artisan.plus@https://roastlocal.ru', 'igor@example.com')] = 'new'
    kr.store[('artisan.plus', 'igor@example.com')] = 'old'
    assert connection.read_saved_password('igor@example.com') == 'new'


def test_delete_removes_both_names(roastlocal:None, kr:_Keyring) -> None:
    del roastlocal
    kr.store[('artisan.plus@https://roastlocal.ru', 'a@b.cc')] = 'x'
    kr.store[('artisan.plus', 'a@b.cc')] = 'y'
    connection.delete_saved_password('a@b.cc')
    assert kr.store == {}
    connection.delete_saved_password('a@b.cc') # nothing left: no error


def test_missing_password_is_none(roastlocal:None, kr:_Keyring) -> None:
    del roastlocal, kr
    res:Any = connection.read_saved_password('nobody@example.com')
    assert res is None
