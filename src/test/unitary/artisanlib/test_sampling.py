"""Regression tests for artisanlib.sampling.SamplingDlg locale robustness.

Bug A: opening Settings -> Sampling crashed with ``babel.core.UnknownLocaleError:
unknown locale 'ru'`` on builds whose bundled babel ships without the UI language's
locale-data (observed on the Windows 'ru' build). SamplingDlg formats the interval
suffix via ``babel.units.get_unit_name(..., locale=aw.locale_str)`` which raised while
constructing the dialog. The dialog must open regardless, falling back to the English
unit name, without regressing the localized output when the locale-data IS available.
"""

import sys
from collections.abc import Generator
from typing import cast
from unittest.mock import Mock

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

import babel.localedata
from babel.core import UnknownLocaleError

from artisanlib.sampling import SamplingDlg


@pytest.fixture(scope='session')
def qapp() -> Generator[QApplication, None, None]: # pyright:ignore[reportUnknownParameterType]
    if not QApplication.instance():
        app = QApplication(sys.argv)
        app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
        yield app
        app.quit()
    else:
        yield cast(QApplication, QApplication.instance())


def _make_aw(locale_str: str) -> Mock:
    aw = Mock()
    aw.locale_str = locale_str
    aw.qmc = Mock()
    aw.qmc.flagKeepON = False
    aw.qmc.flagOpenCompleted = False
    aw.qmc.min_delay = 1000
    aw.qmc.delay = 3000
    aw.qmc.xgrid = 60  # < 3600 -> exercises the 'duration-second' path
    aw.arabicReshape = lambda s: s
    return aw


@pytest.fixture
def break_babel_locale(monkeypatch: pytest.MonkeyPatch):
    """Simulate a build whose babel has no locale-data for the given locale(s)."""
    def _apply(*missing: str) -> None:
        missing_set = set(missing)
        orig_exists = babel.localedata.exists
        orig_load = babel.localedata.load

        def fake_exists(name: object) -> bool:
            return False if str(name) in missing_set else orig_exists(name)

        def fake_load(name: object, merge_inherited: bool = True):  # type: ignore[no-untyped-def]
            if str(name) in missing_set:
                raise UnknownLocaleError(str(name))
            return orig_load(name, merge_inherited)

        monkeypatch.setattr(babel.localedata, 'exists', fake_exists)
        monkeypatch.setattr(babel.localedata, 'load', fake_load)
    return _apply


def test_sampling_dialog_opens_when_locale_data_missing(
    qapp: QApplication, break_babel_locale  # noqa: ARG001
) -> None:
    """Dialog must open (not raise) and fall back to the English unit name."""
    break_babel_locale('ru', 'ru_RU')
    parent = QWidget()
    dlg = SamplingDlg(parent, _make_aw('ru'))
    assert dlg.interval.suffix().strip() == 'secs'  # English fallback, not a crash


def test_sampling_dialog_keeps_localized_unit_when_available(
    qapp: QApplication,  # noqa: ARG001
) -> None:
    """No regression: with locale-data present, the localized unit is still used."""
    parent = QWidget()
    dlg = SamplingDlg(parent, _make_aw('ru'))
    # Russian short unit for seconds is 'с' (Cyrillic es), distinct from English.
    assert dlg.interval.suffix().strip() == 'с'


def test_sampling_dialog_english_unaffected(qapp: QApplication) -> None:  # noqa: ARG001
    parent = QWidget()
    dlg = SamplingDlg(parent, _make_aw('en'))
    assert dlg.interval.suffix().strip() == 'secs'


def test_unit_name_for_falls_back_to_default_when_all_locales_missing(
    qapp: QApplication, break_babel_locale  # noqa: ARG001
) -> None:
    """If even the English fallback is unavailable, the plain default is returned."""
    break_babel_locale('ru', 'ru_RU', 'en')
    parent = QWidget()
    dlg = SamplingDlg(parent, _make_aw('ru'))
    assert dlg.interval.suffix().strip() == 'sec'
