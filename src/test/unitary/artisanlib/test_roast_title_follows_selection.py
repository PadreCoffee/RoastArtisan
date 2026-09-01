"""Regression tests for «title/reference follow the SELECTION» (C56).

Unlike test_roast_title_refresh.py — whose tests call the title-decision helpers
directly — these tests drive the REAL Qt widgets through their REAL signals
(`currentIndexChanged` / `activated` on a live `MyQComboBox`) and exercise the real
`_applyTemplatesToCombo` / `populateTemplateCombo` methods. A broken signal
connection or a missing auto-select therefore makes the test FAIL, which the
direct-call tests cannot catch.

Rules (confirmed by the owner 2026-08-22):
  1. ANY reference selected (manually OR by the system) -> title = reference name.
  2. A bean with NO reference -> the title is not forced to a reference name.
  3. A coffee with zero references -> «Без эталона», no error (normal).
  4. Opening the dialog overwrites nothing: a loaded reference survives, even with
     no coffee/blend in context, and regardless of UUID text format.
  5. With no bean/blend selected, the reference control stays ENABLED and offers the
     machine-scoped references so one can still be picked.
"""

import sys
import types

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main  # noqa: E402,F401  (upgrades the QApplication instance)
import plus.config  # noqa: E402
import plus.stock  # noqa: E402
import plus.util  # noqa: E402
from artisanlib.roast_properties import editGraphDlg  # noqa: E402
from artisanlib.widgets import MyQComboBox  # noqa: E402

ROASTER_SCOPE = QApplication.translate('Scope Title', 'Roaster Scope')
NO_REFERENCE = 'Без эталона'


class _FakeTitleEdit:
    """Minimal stand-in for the RoastsComboBox title widget."""

    def __init__(self, text: str = '') -> None:
        self._text = text

    def currentText(self) -> str:
        return self._text

    def setEditText(self, t: str) -> None:
        self._text = t

    def textEdited(self, t: str) -> None:
        pass


_REAL_METHODS = (
    '_autoTitleCandidate', '_titleIsAutoDerived', '_applyAutoTitle', 'updateTitle',
    '_setTitleFromReference', 'templateSelectionChanged', 'templateReactivated',
    '_applyTemplatesToCombo', 'populateTemplateCombo',
)


def _harness(title='', *, coffee_label=None, coffee_title_label=None, blend_label=None,
             last_auto_title=None, reference_auto_title=None, template_uuid=None,
             template_label=None, user_updated=False, select_after_fetch=False,
             plus_coffee_selected=None, plus_blend_selected_spec=None, wire=True):
    """Stand-in carrying a REAL MyQComboBox wired to the REAL slots, with the real
    editGraphDlg title/template methods bound to it."""
    o = types.SimpleNamespace()
    o.titleedit = _FakeTitleEdit(title)
    o.plus_coffee_selected_label = coffee_label
    o.plus_coffee_title_label = coffee_title_label
    o.plus_blend_selected_label = blend_label
    o.last_auto_title = last_auto_title
    o.reference_auto_title = reference_auto_title
    o.template_uuid = template_uuid
    o.template_file = None
    o.template_label = template_label
    o.template_is_reference = False
    o.plus_templates = []
    o.user_updated_coffee_or_blend = user_updated
    o._select_reference_after_fetch = select_after_fetch
    o.plus_coffee_selected = plus_coffee_selected
    o.plus_blend_selected_spec = plus_blend_selected_spec
    o._updateSnapshotBlock = lambda: None
    o._lotLabel = editGraphDlg._lotLabel
    for name in _REAL_METHODS:
        setattr(o, name, (lambda m: (lambda *a, **k: getattr(editGraphDlg, m)(o, *a, **k)))(name))
    combo = MyQComboBox()
    if wire:
        combo.currentIndexChanged.connect(o.templateSelectionChanged)
        combo.activated.connect(o.templateReactivated)
    o.plus_templates_combo = combo
    return o


def _fill_combo(o, templates):
    """Populate the live combo the way _applyTemplatesToCombo would (blocked), so a later
    user gesture drives the real signal."""
    o.plus_templates = templates
    o.plus_templates_combo.blockSignals(True)
    o.plus_templates_combo.clear()
    o.plus_templates_combo.addItem(NO_REFERENCE)
    for t in templates:
        o.plus_templates_combo.addItem(t.get('label', ''))
    o.plus_templates_combo.setCurrentIndex(0)
    o.plus_templates_combo.blockSignals(False)


REFS = [
    {'uuid': 'a' * 32, 'label': 'Reference Roast #7', '_raw': {}},
    {'uuid': 'b' * 32, 'label': 'Reference Roast #9', '_raw': {}},
]


# --- Rule 1, MANUAL pick through the REAL currentIndexChanged signal -------------------------

def test_rule1_manual_pick_via_real_signal_retitles() -> None:
    o = _harness('El Paraiso', coffee_label='Colombia, El Paraiso',
                 coffee_title_label='El Paraiso', last_auto_title='El Paraiso')
    _fill_combo(o, REFS)
    o.plus_templates_combo.setCurrentIndex(1)          # REAL user gesture
    assert o.titleedit.currentText() == 'Reference Roast #7'
    assert o.template_uuid == 'a' * 32


def test_rule1_manual_repick_same_index_via_activated_retitles() -> None:
    # currentIndexChanged does not fire for an unchanged index; `activated` covers a re-pick
    o = _harness('Reference Roast #7', coffee_label='Colombia, El Paraiso')
    _fill_combo(o, REFS)
    o.plus_templates_combo.blockSignals(True)
    o.plus_templates_combo.setCurrentIndex(1)
    o.template_uuid = 'a' * 32
    o.template_is_reference = True
    o.plus_templates_combo.blockSignals(False)
    o.titleedit.setEditText('Моя обжарка')
    o.plus_templates_combo.activated.emit(1)           # REAL re-pick of the current entry
    assert o.titleedit.currentText() == 'Reference Roast #7'


# --- Rule 1, AUTOMATIC path (the (b) fix): coffee picked -> references arrive ----------------

def test_rule1_auto_select_first_reference_and_retitle() -> None:
    # user just changed the coffee; the title was auto-filled with its lot label; references
    # arrive -> the coffee's reference must be selected and its name pulled into the title.
    o = _harness('El Paraiso', coffee_label='Colombia, El Paraiso',
                 coffee_title_label='El Paraiso', last_auto_title='El Paraiso',
                 template_uuid=None, user_updated=True, select_after_fetch=True,
                 plus_coffee_selected='colombia-el-paraiso')
    o._applyTemplatesToCombo([{'uuid': 'c' * 32, 'label': 'Reference Roast #7', '_raw': {}}])
    assert o.plus_templates_combo.currentIndex() == 1
    assert o.titleedit.currentText() == 'Reference Roast #7'
    assert o.template_uuid == 'c' * 32
    assert o.template_is_reference is True


def test_rule1_auto_select_takes_first_of_several() -> None:
    o = _harness('El Paraiso', coffee_label='Colombia, El Paraiso',
                 coffee_title_label='El Paraiso', last_auto_title='El Paraiso',
                 template_uuid=None, user_updated=True, select_after_fetch=True,
                 plus_coffee_selected='colombia-el-paraiso')
    o._applyTemplatesToCombo(REFS)                     # cloud orders them: lot-matched, then newest
    assert o.plus_templates_combo.currentIndex() == 1
    assert o.titleedit.currentText() == 'Reference Roast #7'


def test_rule1_auto_select_is_one_shot_not_repeated_on_refetch() -> None:
    # after the coffee-pick auto-select, a later stock-update refetch must NOT re-drive the
    # title (the user may have since cleared the reference); the flag is consumed once.
    o = _harness('El Paraiso', coffee_label='Colombia, El Paraiso',
                 coffee_title_label='El Paraiso', last_auto_title='El Paraiso',
                 template_uuid=None, user_updated=True, select_after_fetch=True,
                 plus_coffee_selected='colombia-el-paraiso')
    o._applyTemplatesToCombo(REFS)
    assert o._select_reference_after_fetch is False    # consumed
    # user now clears the reference by hand
    o.plus_templates_combo.setCurrentIndex(0)
    assert o.titleedit.currentText() == 'El Paraiso'
    # a background stock-update refetch arrives — must not re-select the reference
    o._applyTemplatesToCombo(REFS)
    assert o.plus_templates_combo.currentIndex() == 0
    assert o.titleedit.currentText() == 'El Paraiso'


# --- Rule 2: a bean with NO reference does not force a reference name ------------------------

def test_rule2_coffee_with_no_reference_does_not_force_a_reference_title() -> None:
    # coffee picked, its lot label is the title; zero references come back -> title stays the
    # lot label (no reference is fabricated), combo shows «Без эталона».
    o = _harness('El Paraiso', coffee_label='Colombia, El Paraiso',
                 coffee_title_label='El Paraiso', last_auto_title='El Paraiso',
                 template_uuid=None, user_updated=True, select_after_fetch=True,
                 plus_coffee_selected='colombia-el-paraiso')
    o._applyTemplatesToCombo([])
    assert o.plus_templates_combo.currentIndex() == 0
    assert o.titleedit.currentText() == 'El Paraiso'
    assert o.reference_auto_title is None


def test_rule2_fallback_references_not_auto_selected_blend_keeps_its_name() -> None:
    # A blend (or coffee) with NO reference bound to it: getReferencesFromAPI's filtered fetch
    # returns 0, so it retries WITHOUT the coffee/blend filter and returns the machine-wide
    # references, marked `_fallback`. Those are NOT the blend's own references, so the one-shot
    # auto-select must NOT fire — otherwise the title is hijacked to an unrelated reference and
    # that reference is loaded as background. The title must stay the blend name (rule 2), and
    # the combo must offer the fallback references at «Без эталона» (rule 5) for a manual pick.
    o = _harness('My Blend', blend_label='My Blend', last_auto_title='My Blend',
                 template_uuid=None, user_updated=True, select_after_fetch=True,
                 plus_blend_selected_spec={'hr_id': 'blend-1'})
    fallback = [{'uuid': 'a' * 32, 'label': 'Unrelated Machine Ref', '_raw': {}, '_fallback': True},
                {'uuid': 'b' * 32, 'label': 'Another Machine Ref', '_raw': {}, '_fallback': True}]
    o._applyTemplatesToCombo(fallback)
    assert o.titleedit.currentText() == 'My Blend'          # NOT hijacked to a fallback reference
    assert o.plus_templates_combo.currentIndex() == 0        # «Без эталона»
    assert o.template_uuid is None                           # no reference loaded as background
    assert o._select_reference_after_fetch is False          # one-shot consumed
    # rule 5: the fallback references are still offered so the user can pick one by hand
    items = [o.plus_templates_combo.itemText(i) for i in range(o.plus_templates_combo.count())]
    assert 'Unrelated Machine Ref' in items


def test_rule1_bound_references_still_auto_select_after_the_fallback_guard() -> None:
    # Guard against over-correction: genuine references bound to the blend/coffee (from the
    # FILTERED fetch, so NOT marked `_fallback`) must still auto-select and retitle (rule 1).
    o = _harness('My Blend', blend_label='My Blend', last_auto_title='My Blend',
                 template_uuid=None, user_updated=True, select_after_fetch=True,
                 plus_blend_selected_spec={'hr_id': 'blend-1'})
    bound = [{'uuid': 'c' * 32, 'label': 'Blend Reference #1', '_raw': {}}]
    o._applyTemplatesToCombo(bound)
    assert o.plus_templates_combo.currentIndex() == 1
    assert o.titleedit.currentText() == 'Blend Reference #1'
    assert o.template_uuid == 'c' * 32


def test_rule2_typed_title_survives_a_no_reference_coffee_pick() -> None:
    o = _harness('Моя обжарка', coffee_label='Colombia, El Paraiso',
                 coffee_title_label='El Paraiso', last_auto_title=None,
                 template_uuid=None, user_updated=True, select_after_fetch=True,
                 plus_coffee_selected='colombia-el-paraiso')
    o._applyTemplatesToCombo([])
    assert o.titleedit.currentText() == 'Моя обжарка'


# --- Rule 3: a coffee with zero references -> «Без эталона», no error ------------------------

def test_rule3_zero_references_leaves_no_reference_entry_only() -> None:
    o = _harness('El Paraiso', coffee_label='Colombia, El Paraiso',
                 template_uuid=None, user_updated=True, select_after_fetch=True,
                 plus_coffee_selected='colombia-el-paraiso')
    o._applyTemplatesToCombo([])
    items = [o.plus_templates_combo.itemText(i) for i in range(o.plus_templates_combo.count())]
    assert items == [NO_REFERENCE]
    assert o.template_uuid is None


# --- Rule 4: opening the dialog overwrites nothing -------------------------------------------

def test_rule4_pure_open_keeps_a_loaded_reference_missing_from_the_fetch() -> None:
    # user did NOT change the coffee; a saved reference is not returned by the filtered fetch
    # -> it is injected and kept selected, never collapsed to «Без эталона».
    o = _harness('Reference Roast #7', template_uuid='a' * 32,
                 template_label='Reference Roast #7', user_updated=False,
                 select_after_fetch=False)
    o._applyTemplatesToCombo([{'uuid': 'z' * 32, 'label': 'Other', '_raw': {}}])
    assert o.template_uuid == 'a' * 32
    assert o.plus_templates_combo.currentIndex() == 1
    assert o.titleedit.currentText() == 'Reference Roast #7'


def test_rule4_no_coffee_open_preserves_the_loaded_reference() -> None:
    # THE (d2) FIX: opening the dialog on a roast whose beans are free text (no plus_coffee)
    # must not wipe the loaded reference. populateTemplateCombo (scheduler fallback) must keep
    # the seeded template_uuid, not hard-clear it.
    o = _harness('Reference Roast #7', template_uuid='a' * 32,
                 template_label='Reference Roast #7', user_updated=False,
                 plus_coffee_selected=None, plus_blend_selected_spec=None)
    o._getTemplatesFromSchedule = lambda: []           # no scheduler items available
    _real_enabled = plus.config.remote_profile_fetch_enabled
    plus.config.remote_profile_fetch_enabled = lambda: False
    try:
        o.populateTemplateCombo()
    finally:
        plus.config.remote_profile_fetch_enabled = _real_enabled
    assert o.template_uuid == 'a' * 32                  # NOT cleared
    assert o.plus_templates_combo.isEnabled() is True
    assert o.plus_templates_combo.currentIndex() == 1


def test_rule4_uuid_format_mismatch_does_not_duplicate_or_drop() -> None:
    # THE (d3) FIX: the seed is normalized, so a dashed background UUID compares equal to the
    # normalized fetch id — no duplicate entry, correct single selection.
    dashed = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    normalized = plus.util.normalizeUUID(dashed)
    o = _harness('Reference Roast #7', template_uuid=normalized,
                 template_label='Reference Roast #7', user_updated=False)
    o._applyTemplatesToCombo([{'uuid': normalized, 'label': 'Reference Roast #7', '_raw': {}}])
    items = [o.plus_templates_combo.itemText(i) for i in range(o.plus_templates_combo.count())]
    assert items == [NO_REFERENCE, 'Reference Roast #7']   # no duplicate
    assert o.plus_templates_combo.currentIndex() == 1


# --- Rule 5: no bean/blend selected -> the control stays enabled and offers references -------

def test_rule5_no_coffee_keeps_reference_control_enabled_with_references() -> None:
    # THE (c) FIX: with no coffee/blend, populateTemplateCombo must NOT disable the combo; it
    # must fetch the machine-scoped references and offer them for selection.
    machine_refs = [{'uuid': 'a' * 32, 'label': 'Machine Reference', '_raw': {}}]
    o = _harness('', plus_coffee_selected=None, plus_blend_selected_spec=None)
    o._getTemplatesFromSchedule = lambda: machine_refs   # stand in for machine-scoped fetch
    _real_enabled = plus.config.remote_profile_fetch_enabled
    plus.config.remote_profile_fetch_enabled = lambda: False
    try:
        o.populateTemplateCombo()
    finally:
        plus.config.remote_profile_fetch_enabled = _real_enabled
    assert o.plus_templates_combo.isEnabled() is True
    items = [o.plus_templates_combo.itemText(i) for i in range(o.plus_templates_combo.count())]
    assert 'Machine Reference' in items
    # and it can then be picked through the real signal
    o.plus_templates_combo.setCurrentIndex(items.index('Machine Reference'))
    assert o.titleedit.currentText() == 'Machine Reference'
