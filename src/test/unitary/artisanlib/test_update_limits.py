"""Regression test for the artisan.plus replySignal handler (online blank-canvas guard).

"Grey screen" bug class: an exception escaping a Qt slot during Qt's pending repaint aborts
the repaint and leaves the plot canvas blank until restart. ``ApplicationWindow.updateLimits``
is the ``@pyqtSlot`` connected to the upload queue worker's ``replySignal`` and fires on the
CONNECTED (online) path once a roast upload succeeds. A malformed/unexpected server reply must
not propagate out of the slot; it must be swallowed + surfaced in Help >> Errors instead.
"""

import sys
from unittest.mock import Mock

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

# artisanlib.main resolves app paths at import time and needs a live QApplication; it also
# upgrades the instance to the Artisan QApplication subclass that plus.* relies on.
_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main as main_module  # noqa: E402


def _fake_window() -> Mock:
    aw = Mock()
    aw.qmc = Mock()
    aw.qmc.adderror = Mock()
    aw.updatePlusLimits = Mock()
    aw.updatePlusPaidUntil = Mock()
    aw.updatePlusStatus = Mock()
    return aw


def test_update_limits_swallows_exception_and_surfaces_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_module.plus.notifications, 'updateNotifications', lambda *_: None)
    aw = _fake_window()
    aw.updatePlusStatus.side_effect = RuntimeError('simulated bad server reply')

    # must NOT raise out of the slot (a raise here would abort the repaint -> blank chart)
    main_module.ApplicationWindow.updateLimits(aw, 100.0, 1.0, '2026-01-01', 0, [])

    aw.qmc.adderror.assert_called_once()             # surfaced in Help >> Errors


def test_update_limits_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        main_module.plus.notifications, 'updateNotifications',
        lambda *a: calls.append(a),
    )
    aw = _fake_window()

    main_module.ApplicationWindow.updateLimits(aw, 100.0, 1.0, '2026-01-01', 0, [])

    aw.updatePlusLimits.assert_called_once_with(100.0, 1.0)
    aw.updatePlusPaidUntil.assert_called_once_with('2026-01-01')
    aw.updatePlusStatus.assert_called_once()
    aw.qmc.adderror.assert_not_called()              # no error on the happy path
    assert calls == [(0, [])]
