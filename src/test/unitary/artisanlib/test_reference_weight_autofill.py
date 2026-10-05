"""Reference weight auto-fill in Roast Properties (owner's rule).

1. Picking a coffee and/or reference whose reference carries a batch weight fills the weight-in field
   right away (visible in the dialog, not only silently after OK).
2. A weight typed by hand is not auto-updated anymore for this roast.
3. Changing the reference updates the weight again (and drops the "manual" mark).
The "manual" mark of a roast must also be cleared when recording is stopped (OffRecorder), not only
on OFF — otherwise one manual entry blocked the reference weight for every following roast.
"""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401
from artisanlib.roast_properties import editGraphDlg, reference_profile_weight, next_weight_manual_flag  # noqa: E402


def test_reference_profile_weight_parsed(tmp_path) -> None:
    p = tmp_path / 'r.alog'
    p.write_text("{'title': 'x', 'weight': [11.0, 9.35, 'Kg'], 'roastisodate': '2026-06-29'}", encoding='utf-8')
    assert reference_profile_weight(str(p)) == (11.0, 'Kg')
    p.write_text('{"weight": [300, 255, "g"]}', encoding='utf-8')
    assert reference_profile_weight(str(p)) == (300.0, 'g')
    p.write_text("{'weight': [0, 0, 'Kg']}", encoding='utf-8')
    assert reference_profile_weight(str(p)) is None          # no weight bound
    assert reference_profile_weight(None) is None
    assert reference_profile_weight(str(tmp_path / 'missing.alog')) is None


def test_manual_flag_rules() -> None:
    # typed in this dialog -> manual
    assert next_weight_manual_flag(typed=True, was_manual=False, reference_changed=False) is True
    # manual stays while the reference is unchanged
    assert next_weight_manual_flag(typed=False, was_manual=True, reference_changed=False) is True
    # changing the reference drops the manual mark (rule 3)
    assert next_weight_manual_flag(typed=False, was_manual=True, reference_changed=True) is False
    # typed after changing the reference -> manual again
    assert next_weight_manual_flag(typed=True, was_manual=True, reference_changed=True) is True


class _Edit:
    def __init__(self, txt: str) -> None:
        self.txt = txt

    def text(self) -> str:
        return self.txt

    def setText(self, t: str) -> None:
        self.txt = t


def _dlg(typed: bool, manual: bool, ref_changed: bool):
    o = types.SimpleNamespace()
    o.weight_in_user_edited = typed
    o.weightinedit = _Edit('0')
    o.unitsComboBox = types.SimpleNamespace(currentIndex=lambda: 1)       # Kg
    o.template_uuid = 'NEW' if ref_changed else 'OLD'
    o.org_template_uuid = 'OLD'
    o.aw = types.SimpleNamespace(qmc=types.SimpleNamespace(weight_manually_set=manual))
    for m in ('percent', 'calculated_organic_loss', 'recalc_on_density_in_editing_finished'):
        setattr(o, m, lambda *a, **k: None)
    o._referenceWeightAllowed = lambda: True
    return o


def test_fill_when_not_manual() -> None:
    o = _dlg(typed=False, manual=False, ref_changed=False)
    editGraphDlg._setWeightInFromReference(o, 11.0, 'Kg')
    assert o.weightinedit.text() == '11'


def test_no_fill_after_typing_in_this_dialog() -> None:
    o = _dlg(typed=True, manual=False, ref_changed=True)
    editGraphDlg._setWeightInFromReference(o, 11.0, 'Kg')
    assert o.weightinedit.text() == '0'


def test_no_fill_when_roast_weight_manual_and_reference_unchanged() -> None:
    o = _dlg(typed=False, manual=True, ref_changed=False)
    editGraphDlg._setWeightInFromReference(o, 11.0, 'Kg')
    assert o.weightinedit.text() == '0'


def test_fill_again_after_reference_change_even_if_manual_before() -> None:
    o = _dlg(typed=False, manual=True, ref_changed=True)
    editGraphDlg._setWeightInFromReference(o, 11.0, 'Kg')
    assert o.weightinedit.text() == '11'


def test_unit_conversion_g_to_kg() -> None:
    o = _dlg(typed=False, manual=False, ref_changed=False)
    editGraphDlg._setWeightInFromReference(o, 300.0, 'g')
    assert o.weightinedit.text() == '0.3'
