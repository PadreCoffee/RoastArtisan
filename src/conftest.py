# required to run pytest on CI


import os
import sys
import shutil
import atexit
import tempfile
import pytest
import numpy as np # pylint: disable=unused-import
import scipy.optimize # need to import globally to avoid reimport # pylint: disable=unused-import
from typing import Any


####
# Test isolation from the real user environment.
#
# This conftest is imported by pytest before any test module, hence before any app module
# (artisanlib.*, plus.*). Several app modules compute their data/cache paths at import time
# (artisanlib.util.getDataDirectory(), the log file configured in artisanlib.main,
# plus.stock/queue/register/schedule cache paths), and QSettings() / keyring would otherwise
# read and write the developer's real Artisan settings and OS keychain. Everything below
# redirects those into a per-session temporary directory that is removed at exit.

_TEST_ROOT: str = tempfile.mkdtemp(prefix='roastartisan-pytest-')
atexit.register(shutil.rmtree, _TEST_ROOT, ignore_errors=True)
os.environ['ROASTARTISAN_TEST_ROOT'] = _TEST_ROOT

from PyQt6.QtCore import QStandardPaths, QSettings # noqa: E402

# Qt's own test mode already moves the user locations to ~/.qttest/...; on top of that every
# location under the user's home is remapped into _TEST_ROOT so nothing is written to $HOME.
QStandardPaths.setTestModeEnabled(True)

_HOME: str = os.path.expanduser('~')
_orig_standardLocations = QStandardPaths.standardLocations
_orig_writableLocation = QStandardPaths.writableLocation


def _redirect(path:str) -> str:
    if path and (path == _HOME or path.startswith(_HOME + os.sep)):
        return os.path.join(_TEST_ROOT, 'home', os.path.relpath(path, _HOME))
    return path


def _standardLocations(location:QStandardPaths.StandardLocation) -> list[str]:
    return [_redirect(p) for p in _orig_standardLocations(location)]


def _writableLocation(location:QStandardPaths.StandardLocation) -> str:
    return _redirect(_orig_writableLocation(location))


QStandardPaths.standardLocations = staticmethod(_standardLocations) # type: ignore[method-assign,assignment]
QStandardPaths.writableLocation = staticmethod(_writableLocation) # type: ignore[method-assign,assignment]

# QSettings() (the constructor used throughout the app) honours the default format: store all
# settings as INI files below _TEST_ROOT instead of the native macOS plist / Windows registry.
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
for _scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
    QSettings.setPath(QSettings.Format.IniFormat, _scope, os.path.join(_TEST_ROOT, 'settings', _scope.name))

# replace the OS keyring (macOS Keychain, Windows Credential Locker, SecretService) by an
# in-memory backend so tests never read or store real cloud credentials.
import keyring # noqa: E402
import keyring.errors # noqa: E402
from keyring.backend import KeyringBackend # noqa: E402


class InMemoryKeyring(KeyringBackend):
    priority = 1 # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service:str, username:str) -> str|None:
        return self._store.get((service, username))

    def set_password(self, service:str, username:str, password:str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service:str, username:str) -> None:
        try:
            del self._store[(service, username)]
        except KeyError as e:
            raise keyring.errors.PasswordDeleteError(username) from e


keyring.set_keyring(InMemoryKeyring())


####
# allow for platform specific testing
# see https://docs.pytest.org/en/stable/example/markers.html#marking-platform-specific-tests-with-pytest
# use @pytest.mark.darwin, @pytest.mark.linux, @pytest.mark.win32

ALL = set('darwin linux win32'.split())

def pytest_runtest_setup(item:Any) -> None:
    supported_platforms = ALL.intersection(mark.name for mark in item.iter_markers())
    plat = sys.platform
    if supported_platforms and plat not in supported_platforms:
        pytest.skip(f"cannot run on platform {plat}")

# register platform markers
def pytest_configure(config:Any) -> None:
    for plat in ALL:
        config.addinivalue_line(
            'markers', f"{plat}: mark test to run only on named platform")
