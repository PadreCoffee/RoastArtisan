"""Wiring tests for the Roast Properties lot picker (cloud lots mode), driven against a MOCKED
`lots` array (the cloud field is not live yet). Binds the REAL editGraphDlg methods
(_updateLotCombo / lotSelectionChanged / _hideLotCombo) to a light stand-in, so the gating and
selection-tracking logic is exercised without constructing the whole dialog.
"""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401  (upgrades the QApplication instance)
from artisanlib.roast_properties import editGraphDlg  # noqa: E402


class _FakeCombo:
    def __init__(self) -> None:
        self._items: list[str] = []
        self._idx = -1

    def blockSignals(self, _b: bool) -> None:
        pass

    def clear(self) -> None:
        self._items = []
        self._idx = -1

    def addItem(self, t: str) -> None:
        self._items.append(t)
        if self._idx == -1:
            self._idx = 0

    def setCurrentIndex(self, i: int) -> None:
        self._idx = i

    def currentIndex(self) -> int:
        return self._idx

    def count(self) -> int:
        return len(self._items)

    def itemText(self, i: int) -> str:
        return self._items[i]


class _FakeFrame:
    def __init__(self) -> None:
        self.visible = False

    def setVisible(self, b: bool) -> None:
        self.visible = b


class _FakeUnits:
    # weight unit combo; index 1 == 'Kg' (weight_units order: g, Kg, lb, oz)
    def currentIndex(self) -> int:
        return 1


def _harness(prior_lot=None):
    o = types.SimpleNamespace()
    o.plus_lots_combo = _FakeCombo()
    o.plusLineLotsFrame = _FakeFrame()
    o.unitsComboBox = _FakeUnits()
    o.plus_lots_current = []
    o.plus_lot_selected = prior_lot
    o.user_updated_coffee_or_blend = False
    for m in ('_updateLotCombo', '_hideLotCombo', 'lotSelectionChanged'):
        setattr(o, m, (lambda mm: (lambda *a, **k: getattr(editGraphDlg, mm)(o, *a, **k)))(m))
    return o


def _lots(*specs):
    # specs: (id, code, weight_kg[, warehouse])
    out = []
    for s in specs:
        d = {'id': s[0], 'code': s[1], 'weight_kg': s[2]}
        if len(s) > 3:
            d['warehouse_name'] = s[3]
        out.append(d)
    return out


TWO = _lots(('a' * 8, 'L-A', 12.5, 'WH-1'), ('b' * 8, 'L-B', 5.0, 'WH-2'))


def test_no_lots_hides_picker() -> None:
    o = _harness()
    o._updateLotCombo({'hr_id': 'c1'})               # no 'lots' key (SKU mode)
    assert o.plusLineLotsFrame.visible is False
    assert o.plus_lot_selected is None


def test_single_lot_hides_picker() -> None:
    o = _harness()
    o._updateLotCombo({'lots': _lots(('a' * 8, 'L-A', 12.5))})
    assert o.plusLineLotsFrame.visible is False


def test_two_lots_show_picker_preselect_default_omits_lot_id() -> None:
    o = _harness()
    o._updateLotCombo({'lots': TWO})
    assert o.plusLineLotsFrame.visible is True
    assert o.plus_lots_combo.count() == 2
    assert o.plus_lots_combo.currentIndex() == 0                     # cloud default pre-selected
    assert o.plus_lots_combo.itemText(0).startswith('L-A')          # code · weight · warehouse
    assert 'WH-1' in o.plus_lots_combo.itemText(0)
    assert o.plus_lot_selected is None                              # default -> omit lot_id


def test_pick_nondefault_lot_records_id_and_marks_user_change() -> None:
    o = _harness()
    o._updateLotCombo({'lots': TWO})
    o.lotSelectionChanged(1)                                        # roaster picks the 2nd lot
    assert o.plus_lot_selected == 'b' * 8
    assert o.user_updated_coffee_or_blend is True


def test_pick_back_to_default_omits_again() -> None:
    o = _harness()
    o._updateLotCombo({'lots': TWO})
    o.lotSelectionChanged(1)
    o.lotSelectionChanged(0)                                        # back to the default
    assert o.plus_lot_selected is None


def test_prior_choice_survives_reopen() -> None:
    o = _harness(prior_lot='b' * 8)                                 # a lot chosen in a previous open
    o._updateLotCombo({'lots': TWO})
    assert o.plus_lots_combo.currentIndex() == 1                    # pre-selected the prior lot
    assert o.plus_lot_selected == 'b' * 8                           # still uploaded


def test_hide_clears_state() -> None:
    o = _harness()
    o._updateLotCombo({'lots': TWO})
    o._hideLotCombo()
    assert o.plusLineLotsFrame.visible is False
    assert o.plus_lots_current == []
    assert o.plus_lot_selected is None
    assert o.plus_lots_combo.count() == 0
