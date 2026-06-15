"""Regression test for the toolbar "+" (cloud connect/upload) handler.

Bug B: pressing the "+" button to upload the current profile to the cloud could leave
the plot canvas blank (grey screen). ``VMToolbar.plus`` called ``plus.controller.toggle``
unguarded, so any exception escaping that call aborted Qt's pending repaint and nothing
re-issued the draw. The handler must now swallow+log the exception and redraw the canvas
so that neither a failed nor a successful upload ever leaves the chart blank.
"""

import sys
from unittest.mock import Mock

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

# artisanlib.main / plus.controller resolve the app data directory at import time, which
# requires a live QApplication; create one before importing them. Importing artisanlib.main
# also upgrades the instance to the Artisan QApplication subclass that plus.* relies on, so
# it must be imported BEFORE plus.controller.
_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main as main_module  # noqa: E402
import plus.controller  # noqa: E402


def _fake_toolbar() -> Mock:
    tb = Mock()
    tb.aw = Mock()
    tb.aw.qmc = Mock()
    tb.aw.qmc.flagstart = False
    tb.aw.qmc.redraw = Mock()
    tb.aw.qmc.adderror = Mock()
    return tb


def test_plus_swallows_toggle_exception_and_redraws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_aw: object) -> None:
        raise RuntimeError('simulated upload failure')
    monkeypatch.setattr(plus.controller, 'toggle', boom)

    tb = _fake_toolbar()
    # must NOT raise out of the toolbar slot
    main_module.VMToolbar.plus(tb)

    tb.aw.qmc.adderror.assert_called_once()          # surfaced in Help >> Errors
    tb.aw.qmc.redraw.assert_called_once()            # canvas restored, not left blank


def test_plus_redraws_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plus.controller, 'toggle', lambda _aw: None)

    tb = _fake_toolbar()
    main_module.VMToolbar.plus(tb)

    tb.aw.qmc.adderror.assert_not_called()
    tb.aw.qmc.redraw.assert_called_once()            # redrawn afterwards regardless


def test_plus_skips_redraw_while_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plus.controller, 'toggle', lambda _aw: None)

    tb = _fake_toolbar()
    tb.aw.qmc.flagstart = True  # actively recording -> sampling loop owns the redraw
    main_module.VMToolbar.plus(tb)

    tb.aw.qmc.redraw.assert_not_called()
