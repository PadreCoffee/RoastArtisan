"""Snapshot block dates: when were the current green measurement and the reference taken.

The "Зелёное зерно" block compares the coffee's current measurement (mc/aw/density) against the
reference's frozen one. Without dates it is unclear how current either is. snapshot_date() extracts
a display date (DD.MM.YYYY) from the first known date field of the given sources.
"""

import sys

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401
from artisanlib.roast_properties import snapshot_date, reference_profile_date  # noqa: E402


def test_iso_datetime() -> None:
    assert snapshot_date({'measured_at': '2026-10-01T12:34:56Z'}) == '01.10.2026'


def test_iso_date_and_key_priority() -> None:
    assert snapshot_date({'date': '2026-06-29', 'measured_at': '2026-07-01'}) == '01.07.2026'


def test_epoch_ms_and_s() -> None:
    assert snapshot_date({'measured_at': 1790952990073}) is not None
    assert snapshot_date({'measured_at': 1790952990}) == snapshot_date({'measured_at': 1790952990073})


def test_first_source_with_a_date_wins_and_missing_is_none() -> None:
    assert snapshot_date({}, None, {'roasted_at': '2026-01-06'}) == '06.01.2026'
    assert snapshot_date({'mc': 10.0}, None) is None
    assert snapshot_date({'measured_at': 'garbage'}) is None


def test_reference_profile_date_from_cached_alog(tmp_path) -> None:
    p = tmp_path / 'ref.alog'
    p.write_text("{'title': 'x', 'roastisodate': '2026-06-29', 'roasttime': '12:32:15'}", encoding='utf-8')
    assert reference_profile_date(str(p)) == '29.06.2026'
    assert reference_profile_date(None) is None
    assert reference_profile_date(str(tmp_path / 'missing.alog')) is None
