"""Regression tests for roast-title refresh on a COMPLETED roast.

Bug: on a completed roast, changing the coffee/blend and/or reference did not refresh the
roast title («Название»); the old coffee's name stayed and was sent to the cloud. The title
auto-refresh normally rides the coffee/blend combo change-signal, which is blocked on a
completed roast (to protect the stored properties), so the title was never refreshed.

These tests exercise the pure title-decision logic of editGraphDlg without building the full
Qt dialog (which needs a plus account, stock and a loaded profile). They call the real methods
bound to a lightweight stand-in object that carries only the attributes those methods touch.

Key invariants verified:
  * an auto-derived title is refreshed when the coffee/blend selection changes
  * a title that became STALE (shows a prior coffee the selection moved on from) is still
    recognised as auto-derived and refreshed - including across coffee->reference changes
  * a user-TYPED custom title is never overwritten by the coffee/blend auto-derivation
  * picking a reference ALWAYS retitles the roast (explicit user action), and that title then
    outranks the coffee/blend auto-derivation - it is not reverted by a later refresh
"""

import sys
import types

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main  # noqa: E402,F401  (upgrades the QApplication instance)
from artisanlib.roast_properties import editGraphDlg  # noqa: E402

ROASTER_SCOPE = QApplication.translate('Scope Title', 'Roaster Scope')


class _FakeTitleEdit:
    """Minimal stand-in for the RoastsComboBox title widget."""

    def __init__(self, text: str = '') -> None:
        self._text = text

    def currentText(self) -> str:
        return self._text

    def setEditText(self, t: str) -> None:
        self._text = t

    def textEdited(self, t: str) -> None:  # RoastsComboBox.textEdited is a plain method here
        pass


def _dlg(title: str = '', *, coffee_label=None, coffee_title_label=None,
         blend_label=None, last_auto_title=None, reference_auto_title=None):
    """Build a stand-in carrying just the attributes the title methods read, and bind the
    real editGraphDlg methods to it."""
    o = types.SimpleNamespace()
    o.titleedit = _FakeTitleEdit(title)
    o.plus_coffee_selected_label = coffee_label
    o.plus_coffee_title_label = coffee_title_label
    o.plus_blend_selected_label = blend_label
    o.last_auto_title = last_auto_title
    o.reference_auto_title = reference_auto_title
    # bind the real implementations
    o._lotLabel = editGraphDlg._lotLabel
    o._autoTitleCandidate = lambda: editGraphDlg._autoTitleCandidate(o)
    o._titleIsAutoDerived = lambda *p: editGraphDlg._titleIsAutoDerived(o, *p)
    o._applyAutoTitle = lambda t, **kw: editGraphDlg._applyAutoTitle(o, t, **kw)
    o.updateTitle = lambda pc, pb: editGraphDlg.updateTitle(o, pc, pb)
    o._setTitleFromReference = lambda r: editGraphDlg._setTitleFromReference(o, r)
    o.templateSelectionChanged = lambda n: editGraphDlg.templateSelectionChanged(o, n)
    o.templateReactivated = lambda n: editGraphDlg.templateReactivated(o, n)
    o._updateSnapshotBlock = lambda: None
    o.template_uuid = None
    o.template_file = None
    o.template_is_reference = False
    o.plus_templates = []
    return o


# --- _autoTitleCandidate --------------------------------------------------------------------

def test_auto_candidate_blend_wins() -> None:
    o = _dlg(blend_label='House Blend', coffee_label='Ethiopia, Guji')
    assert o._autoTitleCandidate() == 'House Blend'


def test_auto_candidate_coffee_uses_lot_label() -> None:
    o = _dlg(coffee_label='Ethiopia, Guji Shakiso')
    assert o._autoTitleCandidate() == 'Guji Shakiso'


def test_auto_candidate_prefers_explicit_title_label() -> None:
    o = _dlg(coffee_label='Ethiopia, Guji Shakiso', coffee_title_label='Guji')
    assert o._autoTitleCandidate() == 'Guji'


def test_auto_candidate_empty_is_roaster_scope() -> None:
    o = _dlg()
    assert o._autoTitleCandidate() == ROASTER_SCOPE


# --- updateTitle: coffee change on a completed roast (the core bug) --------------------------

def test_updateTitle_refreshes_auto_title_to_new_coffee() -> None:
    # title currently shows the previous coffee's lot; selection has moved to a new coffee
    o = _dlg('Guji Shakiso', coffee_label='Colombia, El Paraiso',
             last_auto_title='Guji Shakiso')
    o.updateTitle('Ethiopia, Guji Shakiso', None)
    assert o.titleedit.currentText() == 'El Paraiso'
    assert o.last_auto_title == 'El Paraiso'


def test_updateTitle_refreshes_empty_title() -> None:
    o = _dlg('', coffee_label='Colombia, El Paraiso')
    o.updateTitle(None, None)
    assert o.titleedit.currentText() == 'El Paraiso'


def test_updateTitle_refreshes_roaster_scope() -> None:
    o = _dlg(ROASTER_SCOPE, coffee_label='Colombia, El Paraiso')
    o.updateTitle(None, None)
    assert o.titleedit.currentText() == 'El Paraiso'


def test_updateTitle_never_overwrites_custom_title() -> None:
    o = _dlg('My Special Roast', coffee_label='Colombia, El Paraiso',
             last_auto_title='Guji Shakiso')  # last auto was something else; current is custom
    o.updateTitle('Ethiopia, Guji Shakiso', None)
    assert o.titleedit.currentText() == 'My Special Roast'
    assert o.last_auto_title == 'Guji Shakiso'  # unchanged


def test_updateTitle_strand_via_last_auto_title() -> None:
    # title is stale (prior coffee lot) and the prev label no longer matches it, but it equals
    # the value we last auto-applied -> still recognised as auto-derived and refreshed
    o = _dlg('Guji Shakiso', coffee_label='Colombia, El Paraiso',
             last_auto_title='Guji Shakiso')
    o.updateTitle(None, None)  # no prev labels supplied
    assert o.titleedit.currentText() == 'El Paraiso'


# --- _setTitleFromReference: coffee -> reference in sequence ---------------------------------

def test_reference_overwrites_current_coffee_title() -> None:
    o = _dlg('El Paraiso', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title='El Paraiso')
    o._setTitleFromReference('Reference Roast #7')
    assert o.titleedit.currentText() == 'Reference Roast #7'
    assert o.last_auto_title == 'Reference Roast #7'


def test_reference_overwrites_stale_prior_coffee_title() -> None:
    # THE STRAND: coffee changed (title stale = old lot), then a reference is picked.
    # current coffee label no longer matches the displayed title, but last_auto_title does.
    o = _dlg('Guji Shakiso', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title='Guji Shakiso')
    o._setTitleFromReference('Reference Roast #7')
    assert o.titleedit.currentText() == 'Reference Roast #7'


def test_reference_overwrites_empty_title() -> None:
    o = _dlg('', coffee_label='Colombia, El Paraiso')
    o._setTitleFromReference('Reference Roast #7')
    assert o.titleedit.currentText() == 'Reference Roast #7'


def test_reference_overwrites_custom_title() -> None:
    # picking a reference is an explicit user action: the title always follows the reference
    o = _dlg('My Special Roast', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title=None)
    o._setTitleFromReference('Reference Roast #7')
    assert o.titleedit.currentText() == 'Reference Roast #7'


def test_reference_overwrites_title_left_by_an_earlier_reference() -> None:
    # THE REPORTED BUG: the roast was reopened, so its saved reference-derived title is not
    # recognised as coffee/blend-derived (last_auto_title is None). Picking another reference
    # must still retitle the roast.
    o = _dlg('Reference Roast #7', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title=None)
    o._setTitleFromReference('Reference Roast #9')
    assert o.titleedit.currentText() == 'Reference Roast #9'


# --- a reference title outranks the coffee/blend auto-title ----------------------------------

def test_reference_title_survives_a_later_coffee_refresh() -> None:
    # THE REPORTED BUG (second strand): after picking a reference, any repopulate of the
    # coffee/blend combos (stock update, weight-unit change, ...) runs updateTitle(); it must
    # not revert the reference title to the coffee lot label.
    o = _dlg('El Paraiso', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title='El Paraiso')
    o._setTitleFromReference('Reference Roast #7')
    o.updateTitle(o.plus_coffee_selected_label, o.plus_blend_selected_label)
    assert o.titleedit.currentText() == 'Reference Roast #7'


def test_reference_title_survives_a_coffee_change() -> None:
    o = _dlg('Guji Shakiso', coffee_label='Ethiopia, Guji Shakiso',
             coffee_title_label='Guji Shakiso', last_auto_title='Guji Shakiso')
    o._setTitleFromReference('Reference Roast #7')
    # user now switches the coffee -> the reference still names the roast
    o.plus_coffee_selected_label = 'Colombia, El Paraiso'
    o.plus_coffee_title_label = 'El Paraiso'
    o.updateTitle('Ethiopia, Guji Shakiso', None)
    assert o.titleedit.currentText() == 'Reference Roast #7'


def test_clearing_the_reference_falls_back_to_the_coffee_title() -> None:
    # «Без эталона» (index 0) while the title still shows the reference name
    o = _dlg('El Paraiso', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title='El Paraiso')
    o._setTitleFromReference('Reference Roast #7')
    o.templateSelectionChanged(0)
    assert o.titleedit.currentText() == 'El Paraiso'
    assert o.reference_auto_title is None


def test_clearing_the_reference_keeps_a_custom_title() -> None:
    o = _dlg('El Paraiso', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title='El Paraiso')
    o._setTitleFromReference('Reference Roast #7')
    o.titleedit.setEditText('My Special Roast')
    o.templateSelectionChanged(0)
    assert o.titleedit.currentText() == 'My Special Roast'


def test_title_typed_after_the_reference_is_protected_again() -> None:
    # the user types a custom title after picking a reference: it is no longer the reference
    # title, so the normal custom-title protection applies to the coffee/blend refresh
    o = _dlg('El Paraiso', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title='El Paraiso')
    o._setTitleFromReference('Reference Roast #7')
    o.titleedit.setEditText('My Special Roast')
    o.updateTitle(o.plus_coffee_selected_label, o.plus_blend_selected_label)
    assert o.titleedit.currentText() == 'My Special Roast'


# --- the full three-step user flow -----------------------------------------------------------

def _reference_combo(o, templates) -> None:
    """Attach a reference list to the stand-in so the combo slots can be driven by index."""
    o.plus_templates = templates


def test_flow_reference_then_manual_edit_then_reference_again() -> None:
    """1) pick a reference -> title becomes the reference title
       2) reopen and type a title by hand -> the typed title stays (survives every auto-refresh)
       3) pick a reference again -> title becomes the reference title again"""
    refs = [{'uuid': 'a' * 32, 'label': 'Reference Roast #7', '_raw': {}},
            {'uuid': 'b' * 32, 'label': 'Reference Roast #9', '_raw': {}}]

    # --- session 1: coffee selected, title auto-filled from its lot; user picks a reference
    o = _dlg('El Paraiso', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso', last_auto_title='El Paraiso')
    _reference_combo(o, refs)
    o.templateSelectionChanged(1)
    assert o.titleedit.currentText() == 'Reference Roast #7'
    saved_title = o.titleedit.currentText()

    # --- session 2: dialog reopened on that roast; the user types a title by hand
    o = _dlg(saved_title, coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso')  # last_auto_title/reference_auto_title unseeded
    _reference_combo(o, refs)
    o.titleedit.setEditText('Моя обжарка')
    # any later combo repopulate (stock update, unit change, ...) must not touch it
    o.updateTitle(o.plus_coffee_selected_label, o.plus_blend_selected_label)
    assert o.titleedit.currentText() == 'Моя обжарка'
    saved_title = o.titleedit.currentText()

    # --- session 3: dialog reopened again; the user picks a reference
    o = _dlg(saved_title, coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso')
    _reference_combo(o, refs)
    o.templateSelectionChanged(2)
    assert o.titleedit.currentText() == 'Reference Roast #9'


def test_repicking_the_same_reference_restores_the_title() -> None:
    # currentIndexChanged does not fire for an unchanged index — the activated slot covers it
    refs = [{'uuid': 'a' * 32, 'label': 'Reference Roast #7', '_raw': {}}]
    o = _dlg('Reference Roast #7', coffee_label='Colombia, El Paraiso',
             coffee_title_label='El Paraiso')
    _reference_combo(o, refs)
    o.template_uuid = 'a' * 32
    o.template_is_reference = True
    o.titleedit.setEditText('Моя обжарка')
    o.templateReactivated(1)
    assert o.titleedit.currentText() == 'Reference Roast #7'


def test_reactivating_index_zero_leaves_the_title_alone() -> None:
    refs = [{'uuid': 'a' * 32, 'label': 'Reference Roast #7', '_raw': {}}]
    o = _dlg('Моя обжарка', coffee_label='Colombia, El Paraiso')
    _reference_combo(o, refs)
    o.templateReactivated(0)
    assert o.titleedit.currentText() == 'Моя обжарка'
