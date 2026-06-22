"""Regression test for roast-title auto-fill from a selected coffee.

Reported: when a coffee is picked in Roast Properties, the title was auto-filled with the
full coffee label "<country>, <lot>" (e.g. "Эфиопия, Guji Shakiso"). The country is
typically already part of the lot name, so the owner wants just the lot label.

editGraphDlg._lotLabel() strips the leading country from a coffeeLabel()-rendered string.
coffeeLabel() renders coffees as "<country>, <lot>" where the country never contains ", ",
so everything after the first ", " is the lot label (which may itself contain commas).
"""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main  # noqa: E402,F401  (upgrades the QApplication instance)
from artisanlib.roast_properties import editGraphDlg  # noqa: E402

_lot = editGraphDlg._lotLabel


def test_strips_leading_country() -> None:
    assert _lot('Ethiopia, Guji Shakiso') == 'Guji Shakiso'


def test_strips_country_with_picked_year() -> None:
    # coffeeLabel() may append the picked year to the country for disambiguation
    assert _lot('Ethiopia 2024, Guji Shakiso') == 'Guji Shakiso'


def test_keeps_label_without_country_unchanged() -> None:
    assert _lot('Guji Shakiso') == 'Guji Shakiso'


def test_keeps_commas_inside_the_lot_label() -> None:
    # only the FIRST ", " (country separator) is dropped; commas inside the lot survive
    assert _lot('Colombia, Finca El Paraiso, Lot 7') == 'Finca El Paraiso, Lot 7'


def test_empty_and_none() -> None:
    assert _lot('') == ''
    assert _lot(None) == ''
