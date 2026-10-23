"""Canvas side of the empty-stock rule: applyRoastStockGuard clears the selection for a NEW batch and tells
the operator; it never touches a batch already CHARGEd; the async stock refresh re-checks only before CHARGE."""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401
import plus.stock  # noqa: E402
from artisanlib.canvas import tgraphcanvas  # noqa: E402

EMPTY = {'coffees': [{'hr_id': 'C1', 'label': 'Колумбия', 'origin': '',
                      'stock': [{'location_hr_id': 'S1', 'location_label': 'S1', 'amount': 0.0}]}]}
FULL = {'coffees': [{'hr_id': 'C1', 'label': 'Колумбия', 'origin': '',
                     'stock': [{'location_hr_id': 'S1', 'location_label': 'S1', 'amount': 12.0}]}]}


def _q(charge: int = -1, account: object = 'acc'):
    msgs: list = []
    q = types.SimpleNamespace(
        timeindex=[charge, 0, 0, 0, 0, 0, 0, 0], flagon=True,
        plus_coffee='C1', plus_coffee_label='Колумбия', plus_store='S1', plus_lot_id='L1',
        plus_blend_spec=None, plus_blend_label=None, plus_blend_spec_labels=None,
        stock_guard_pending=False,
        aw=types.SimpleNamespace(plus_account=account, sendmessage=lambda m, *a, **k: msgs.append(m)))
    q.showStockGuardMessage = lambda text: msgs.append(('box', text))
    q.applyRoastStockGuard = lambda: tgraphcanvas.applyRoastStockGuard(q)
    return q, msgs


def test_empty_stock_clears_coffee_and_lot_and_tells_operator(monkeypatch) -> None:
    monkeypatch.setattr(plus.stock, 'stock', EMPTY)
    q, msgs = _q()
    tgraphcanvas.applyRoastStockGuard(q)
    assert q.plus_coffee is None and q.plus_coffee_label is None and q.plus_lot_id is None
    assert any('Остаток „Колумбия“ — 0 кг' in str(m) for m in msgs)


def test_stocked_coffee_is_kept(monkeypatch) -> None:
    monkeypatch.setattr(plus.stock, 'stock', FULL)
    q, msgs = _q()
    tgraphcanvas.applyRoastStockGuard(q)
    assert q.plus_coffee == 'C1' and q.plus_lot_id == 'L1' and msgs == []


def test_batch_already_charged_is_never_touched(monkeypatch) -> None:
    monkeypatch.setattr(plus.stock, 'stock', EMPTY)
    q, msgs = _q(charge=5)
    tgraphcanvas.applyRoastStockGuard(q)
    assert q.plus_coffee == 'C1' and msgs == []


def test_no_cloud_account_does_nothing(monkeypatch) -> None:
    monkeypatch.setattr(plus.stock, 'stock', EMPTY)
    q, msgs = _q(account=None)
    tgraphcanvas.applyRoastStockGuard(q)
    assert q.plus_coffee == 'C1' and msgs == []


def test_refresh_rechecks_only_while_pending_and_before_charge(monkeypatch) -> None:
    monkeypatch.setattr(plus.stock, 'stock', EMPTY)
    q, _ = _q()
    tgraphcanvas.stockGuardRecheck(q)                 # not pending -> nothing
    assert q.plus_coffee == 'C1'
    q.stock_guard_pending = True
    tgraphcanvas.stockGuardRecheck(q)
    assert q.plus_coffee is None and q.stock_guard_pending is False
    q2, _ = _q(charge=3)
    q2.stock_guard_pending = True
    tgraphcanvas.stockGuardRecheck(q2)                # CHARGE already set -> keep, just disarm
    assert q2.plus_coffee == 'C1' and q2.stock_guard_pending is False


def test_check_runs_on_cached_stock_when_offline_and_never_crashes(monkeypatch) -> None:
    for s in (None, {}, 'garbage'):
        monkeypatch.setattr(plus.stock, 'stock', s)
        q, msgs = _q()
        tgraphcanvas.applyRoastStockGuard(q)
        assert q.plus_coffee == 'C1' and msgs == []
