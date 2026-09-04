"""Regression test: opening Roast Properties must NOT auto-change the background.

Bug: on a not-yet-complete roast, populatePlusCoffeeBlendCombos seeds the coffee combo with
signals UNBLOCKED, firing coffeeSelectionChanged as if the user re-picked the coffee. That set
`user_updated_coffee_or_blend=True` and `_select_reference_after_fetch=True`, which then made
_applyTemplatesToCombo drop the retained (manually-loaded) reference and auto-select the coffee's
bound reference — clobbering a background the roaster had set by hand (loaded on accept()).

Fix: a `_seeding_combos` guard set during populatePlusCoffeeBlendCombos, so those two "user pick"
side effects fire ONLY on a genuine user selection, never on the programmatic open-seeding. A real
coffee pick (not seeding) still arms the reference auto-select (C56 rule 1).
"""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401
import plus.stock  # noqa: E402
from artisanlib.roast_properties import editGraphDlg  # noqa: E402


def _harness(seeding: bool):
    o = types.SimpleNamespace()
    o._seeding_combos = seeding
    o.user_updated_coffee_or_blend = False
    o._select_reference_after_fetch = False
    o.plus_coffee_selected_label = None
    o.plus_blend_selected_label = None
    o.plus_coffee_selected = None
    o.plus_coffee_title_label = None
    o.plus_blend_selected_spec = None
    o.plus_blend_selected_spec_labels = None
    o.plus_store_selected = None
    o.plus_store_selected_label = None
    o.plus_amount_selected = None
    o.plus_amount_replace_selected = None
    o.plus_coffees = ['COFFEE0']  # one coffee; index n=1 selects it
    # stub combos + downstream methods (side-effect-free)
    o.plus_blends_combo = types.SimpleNamespace(setCurrentIndex=lambda i: None)
    for m in ('_updateLotCombo', 'fillCoffeeData', 'checkWeightIn',
              'updatePlusSelectedLine', 'populateTemplateCombo', 'defaultCoffeeData',
              'updateTitle', '_hideLotCombo'):
        setattr(o, m, lambda *a, **k: None)
    # bind the REAL coffeeSelectionChanged
    o.coffeeSelectionChanged = lambda n: editGraphDlg.coffeeSelectionChanged(o, n)
    return o


def _mock_stock(monkeypatch):
    monkeypatch.setattr(plus.stock, 'getCoffeeStockDict',
                        lambda c: {'location_hr_id': 'L1', 'location_label': 'Store 1', 'amount': 5.0})
    monkeypatch.setattr(plus.stock, 'getCoffeeCoffeeDict',
                        lambda c: {'hr_id': 'colombia-el-paraiso', 'label': 'El Paraiso'})
    monkeypatch.setattr(plus.stock, 'coffeeLabel', lambda cd: 'Colombia, El Paraiso')


def test_open_seeding_does_not_arm_user_pick_side_effects(monkeypatch) -> None:
    # simulate the open-seeding: coffeeSelectionChanged fired programmatically while seeding
    o = _harness(seeding=True)
    _mock_stock(monkeypatch)
    o.coffeeSelectionChanged(1)
    # the coffee data IS applied (selection state set)...
    assert o.plus_coffee_selected == 'colombia-el-paraiso'
    # ...but the "user pick" side effects must NOT fire on a pure open:
    assert o.user_updated_coffee_or_blend is False   # would drop a retained/manual reference
    assert o._select_reference_after_fetch is False   # would auto-select the coffee's ref -> clobber bg


def test_genuine_pick_still_arms_side_effects(monkeypatch) -> None:
    # a real user coffee pick (not seeding) must still arm both (C56 rule 1 preserved)
    o = _harness(seeding=False)
    _mock_stock(monkeypatch)
    o.coffeeSelectionChanged(1)
    assert o.plus_coffee_selected == 'colombia-el-paraiso'
    assert o.user_updated_coffee_or_blend is True
    assert o._select_reference_after_fetch is True
