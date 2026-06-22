"""Contract test for localized weight-unit display.

weight_unit_display() localizes the visible unit text (kg→кг, g→г in Russian) while the
canonical keys ('g','Kg','lb','oz') used for indexing/conversion stay untouched. Critically,
with NO translator installed (as in tests, and in the English UI) it must return the source
key unchanged — this is what keeps render_weight()'s output and every weight round-trip stable.
"""

import sys

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from artisanlib.util import weight_unit_display, render_weight  # noqa: E402


def test_no_translator_returns_canonical_keys() -> None:
    # without an installed translator the source text is returned verbatim
    assert weight_unit_display('Kg') == 'kg'
    assert weight_unit_display('kg') == 'kg'
    assert weight_unit_display('g') == 'g'


def test_non_metric_units_pass_through() -> None:
    assert weight_unit_display('lb') == 'lb'
    assert weight_unit_display('oz') == 'oz'
    assert weight_unit_display('t') == 't'


def test_render_weight_unit_text_unchanged_without_translator() -> None:
    # the visible render must stay English when no RU translator is active (keeps tests/EN stable)
    assert render_weight(2.0, 1, 1) == '2kg'
    assert render_weight(500.0, 0, 0) == '500g'
