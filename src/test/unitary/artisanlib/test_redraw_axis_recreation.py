"""Regression test for the "grey screen" blank-canvas ROOT CAUSE.

Confirmed from a Windows client trace ([greyscreen] instrumentation): roastReport() -- the
"PDF Report" autosave path run on roast completion -- calls flavorchart(), which sets
qmc.ax = None (and clears the figure) to render the cupping chart, then calls redraw() to
restore the profile chart. But redraw() could NOT rebuild from `self.ax is None`: its
axis-recreation block sat inside the `elif self.ax is not None:` branch, so with ax None
redraw() fell through every branch and became a silent no-op -- the chart stayed blank until
the client was restarted, with no exception and nothing in the log. flavorchart() and
graphwheel() rely on the same "remove the axis, let redraw() recreate it" contract.

tgraphcanvas._ensureStandardAxis() recreates the standard (and twin delta) axis when it was
removed; redraw() calls it on the no-ax path so it can never be a silent no-op again.
"""

import sys
from unittest.mock import Mock

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from matplotlib.figure import Figure

# artisanlib.canvas resolves app paths at import time and needs the Artisan QApplication
# subclass; importing artisanlib.main first upgrades the live QApplication instance to it.
_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main  # noqa: E402,F401  (upgrades the QApplication instance)
import artisanlib.canvas as canvas_module  # noqa: E402


def _qmc_with_real_figure() -> Mock:
    qmc = Mock()
    qmc.fig = Figure()
    qmc.ax = None
    qmc.delta_ax = None
    qmc.palette = {'background': 'white'}
    return qmc


def test_ensure_axis_recreates_when_removed() -> None:
    qmc = _qmc_with_real_figure()
    canvas_module.tgraphcanvas._ensureStandardAxis(qmc)
    assert qmc.ax is not None         # standard profile axis rebuilt (no longer a silent no-op)
    assert qmc.delta_ax is not None   # twin delta axis rebuilt


def test_ensure_axis_keeps_existing_axis() -> None:
    qmc = _qmc_with_real_figure()
    existing = qmc.fig.add_subplot(111)
    qmc.ax = existing
    sentinel_delta = Mock()
    qmc.delta_ax = sentinel_delta
    canvas_module.tgraphcanvas._ensureStandardAxis(qmc)
    assert qmc.ax is existing          # left untouched when the axis is already present
    assert qmc.delta_ax is sentinel_delta
