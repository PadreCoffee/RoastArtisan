"""The explicit RESET button clears its loaded background after a confirmed reset."""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401
from artisanlib.canvas import tgraphcanvas  # noqa: E402


def test_reset_button_clears_background_after_success() -> None:
    calls = []
    canvas = types.SimpleNamespace(
        disconnectProbes=lambda: calls.append('disconnect'),
        reset=lambda: calls.append('reset') or True,
        aw=types.SimpleNamespace(clearbackgroundRedraw=lambda: calls.append('clear')),
    )
    tgraphcanvas.resetButtonAction(canvas)
    assert calls == ['disconnect', 'reset', 'clear']


def test_cancelled_reset_keeps_background() -> None:
    calls = []
    canvas = types.SimpleNamespace(
        disconnectProbes=lambda: calls.append('disconnect'),
        reset=lambda: calls.append('reset') or False,
        aw=types.SimpleNamespace(clearbackgroundRedraw=lambda: calls.append('clear')),
    )
    tgraphcanvas.resetButtonAction(canvas)
    assert calls == ['disconnect', 'reset']
