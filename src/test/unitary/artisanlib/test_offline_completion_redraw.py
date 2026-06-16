"""Regression test for the automatic roast-completion (OFF/DROP) blank-canvas guard.

"Grey screen" bug: finishing a roast while artisan.plus is unreachable runs the cloud-sync /
upload-queue completion path; an exception escaping a Qt slot there could abort Qt's pending
repaint and nothing re-issued the draw, leaving the plot canvas blank until restart. The
manual "+" button was hardened earlier (see test_plus_toolbar.py); the automatic OFF path had
the same gap. ``tgraphcanvas.guaranteeCanvasRedraw`` is scheduled as the final paint of the
OFF sequence and must re-issue a full redraw without ever raising, and must defer to the
sampling loop while a recording is still active.
"""

import sys
from unittest.mock import Mock

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

# artisanlib.canvas resolves app paths at import time and needs the Artisan QApplication
# subclass; importing artisanlib.main first upgrades the live QApplication instance to it.
_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main  # noqa: E402,F401  (upgrades the QApplication instance)
import artisanlib.canvas as canvas_module  # noqa: E402


def _fake_canvas() -> Mock:
    qmc = Mock()
    qmc.flagstart = False
    qmc.redraw = Mock()
    return qmc


def test_guarantee_redraws_when_not_recording() -> None:
    qmc = _fake_canvas()
    canvas_module.tgraphcanvas.guaranteeCanvasRedraw(qmc)
    qmc.redraw.assert_called_once()                  # canvas restored, not left blank


def test_guarantee_swallows_redraw_exception() -> None:
    qmc = _fake_canvas()
    qmc.redraw.side_effect = RuntimeError('simulated redraw failure')
    # must NOT raise out of the QTimer slot (a raise here would re-abort the repaint)
    canvas_module.tgraphcanvas.guaranteeCanvasRedraw(qmc)
    qmc.redraw.assert_called_once()


def test_guarantee_skips_redraw_while_recording() -> None:
    qmc = _fake_canvas()
    qmc.flagstart = True                             # sampling loop owns the redraw
    canvas_module.tgraphcanvas.guaranteeCanvasRedraw(qmc)
    qmc.redraw.assert_not_called()
