"""Regression tests for CompletedItem.update_completed_item None-handling.

amount / end_weight / defects_weight are non-suppressed server fields (plus/roast.py):
always sent, and may arrive as null (a roast never weighed out, or the pre-v3.1.2
defects_weight). The guard must SKIP a null (leave the real/estimated weight intact),
never coerce it to 0 — coercing would persist a real weight as 0 into the completed-roasts
cache. Mirrors the skip-on-None guards in plus/sync.py applyServerUpdates.
"""

import sys
import uuid as uuidlib
import datetime

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401  (upgrades the QApplication instance)
import plus.schedule  # noqa: E402
from plus.schedule import CompletedItem  # noqa: E402


def _completed_item(**overrides: object) -> CompletedItem:
    kwargs: dict = dict(
        count=1, scheduleID='sch-1', scheduleDate='2026-08-26', sequence_id=1,
        roastUUID=uuidlib.uuid4(), roastdate=datetime.datetime(2026, 8, 26, 12, 0, 0),
        roastbatchnr=1, roastbatchprefix='RA', title='Test Roast',
        batchsize=3.0, weight=2.5, weight_estimate=2.5, defects_weight=0.1,
        color=100.0, moisture=11.0, density=700.0, cupping_score=85.0,
        blend_label='My Blend',
    )
    kwargs.update(overrides)
    return CompletedItem(**kwargs)


def test_update_completed_item_skips_none_weights_without_crash_or_zeroing() -> None:
    # a completed-roast server record that was never weighed out: the three non-suppressed
    # weight fields arrive as null. Must NOT crash (was float(None)) and must NOT zero the
    # real greens/roasted/defects weights already held.
    ci = _completed_item(batchsize=3.0, weight=2.5, defects_weight=0.1)
    updated = ci.update_completed_item(object(), {
        'amount': None, 'end_weight': None, 'defects_weight': None})
    assert updated is False          # nothing changed -> no add_completed, aw untouched
    assert ci.batchsize == 3.0       # real greens weight preserved
    assert ci.weight == 2.5          # real roasted weight preserved
    assert ci.defects_weight == 0.1  # real defects weight preserved


def test_update_completed_item_applies_real_weights(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ci = _completed_item(batchsize=3.0, weight=2.5, defects_weight=0.1)
    persisted: dict = {}
    monkeypatch.setattr(plus.schedule, 'add_completed',
                        lambda acc, d: persisted.update({'acc': acc}))

    class _AW:
        plus_account_id = 'acc-1'

    updated = ci.update_completed_item(_AW(), {'end_weight': 2.7, 'amount': 3.2})
    assert updated is True
    assert ci.weight == 2.7          # real value applied
    assert ci.batchsize == 3.2
    assert persisted.get('acc') == 'acc-1'  # cache update ran
