"""switchOperator points the app at a saved account and authenticates silently."""
import sys
from unittest.mock import Mock

# Mock heavy modules that have Qt app-level deps before importing controller
for _mod in ('plus.stock', 'plus.queue', 'plus.sync', 'plus.roast', 'plus.util'):
    if _mod not in sys.modules:
        sys.modules[_mod] = Mock()

from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)
import plus.config as config         # noqa: E402
import plus.controller as controller   # noqa: E402
import plus.connection as connection   # noqa: E402


def _patch(obj, attr, value):
    """Save original, set new, return restorer."""
    orig = getattr(obj, attr)
    setattr(obj, attr, value)
    return lambda: setattr(obj, attr, orig)


def test_switch_operator_sets_account_and_authenticates():
    aw = Mock()
    aw.qmc = Mock()
    aw.qmc.operator = 'Old'
    aw.plus_account = 'old@x.io'
    config.app_window = aw

    cleared = {}
    restore = [
        _patch(connection, 'clearCredentials',
               lambda remove_from_keychain=True: cleared.update(rk=remove_from_keychain)),
        _patch(connection, 'authentify', lambda: True),
        _patch(connection, 'getNickname', lambda: 'Мария'),
    ]
    try:
        ok = controller.switchOperator('maria@x.io', server_url='https://artisan.plus')
        assert ok is True
        assert cleared['rk'] is False                 # saved passwords preserved
        assert aw.plus_account == 'maria@x.io'         # pointed at new account
        assert aw.qmc.operator == 'Мария'              # operator synced from nickname (forced)
    finally:
        for r in restore:
            r()


def test_switch_operator_auth_failure_returns_false():
    aw = Mock()
    aw.qmc = Mock()
    aw.plus_account = 'old@x.io'
    config.app_window = aw

    restore = [
        _patch(connection, 'clearCredentials', lambda remove_from_keychain=True: None),
        _patch(connection, 'authentify', lambda: False),
    ]
    try:
        assert controller.switchOperator('maria@x.io', server_url='https://artisan.plus') is False
    finally:
        for r in restore:
            r()
