"""Regression test: autoDRY/autoFCs must count from the turning point of the CURRENT charge.

Bug: the TP index (TPalarmtimeindex) was only cleared by reset()/OnMonitor, never when CHARGE was
undone or re-marked. A stale TP from an undone/early (auto-)CHARGE (or the 2-min "TP by timer"
fallback taken while BT was still at preheat level) then (a) blocked TP detection for the real
charge — the TP was never marked again — and (b) unlocked autoDRY/autoFCs right after the new
CHARGE, where they fired on "BT >= threshold" alone while BT was still high: DRY and FCs in a row.

Fix: a TP is only valid if it lies after the current CHARGE (stale ones are dropped so TP is
re-detected), and autoDRY/autoFCs fire only on a genuine rise from that TP: BT at TP below the phase
threshold and BT now at/above it.
"""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401
from artisanlib.canvas import tgraphcanvas  # noqa: E402

DRY, FCS = 150.0, 196.0


def _q(tp: int|None, charge: int, temp2: list[float], after_tp: bool = True):
    return types.SimpleNamespace(TPalarmtimeindex=tp, timeindex=[charge, 0, 0, 0, 0, 0, 0, 0],
                                 temp2=temp2, afterTP=after_tp)


def _reached(q, threshold: float, bt_now: float) -> bool:
    return tgraphcanvas.autoPhaseMarkReached(q, threshold, bt_now)


def test_genuine_rise_from_tp_marks_dry_and_fcs() -> None:
    #           charge                TP
    temp2 = [210.0, 205.0, 160.0, 120.0, 95.0, 100.0, 140.0, 160.0]
    q = _q(tp=4, charge=0, temp2=temp2)
    assert _reached(q, DRY, 151.0) is True
    assert _reached(q, FCS, 197.0) is True


def test_not_yet_at_threshold_does_not_mark() -> None:
    q = _q(tp=4, charge=0, temp2=[210.0, 205.0, 160.0, 120.0, 95.0, 100.0])
    assert _reached(q, DRY, 140.0) is False


def test_tp_taken_while_bt_still_high_never_unlocks_marks() -> None:
    # TP index set right after charge while BT is still above both thresholds (stale/early/fallback TP)
    q = _q(tp=1, charge=0, temp2=[210.0, 205.0, 200.0])
    assert _reached(q, DRY, 200.0) is False
    assert _reached(q, FCS, 200.0) is False


def test_tp_from_before_the_current_charge_does_not_count() -> None:
    # TP left over from an undone CHARGE at idx 2; the roaster re-CHARGEd at idx 10
    temp2 = [200.0, 150.0, 95.0, 120.0, 180.0, 200.0, 205.0, 205.0, 205.0, 205.0, 210.0, 200.0]
    q = _q(tp=2, charge=10, temp2=temp2)
    assert _reached(q, DRY, 200.0) is False
    assert _reached(q, FCS, 200.0) is False


def test_no_tp_never_marks() -> None:
    q = _q(tp=None, charge=0, temp2=[210.0, 100.0, 200.0])
    assert _reached(q, DRY, 200.0) is False


def test_stale_tp_is_dropped_so_it_gets_detected_again() -> None:
    q = _q(tp=2, charge=10, temp2=[0.0] * 12)       # TP before the current CHARGE
    tgraphcanvas.invalidateStaleTP(q)
    assert q.TPalarmtimeindex is None and q.afterTP is False


def test_tp_dropped_when_charge_undone() -> None:
    q = _q(tp=5, charge=-1, temp2=[0.0] * 8)        # CHARGE undone
    tgraphcanvas.invalidateStaleTP(q)
    assert q.TPalarmtimeindex is None and q.afterTP is False


def test_valid_tp_is_kept() -> None:
    q = _q(tp=5, charge=1, temp2=[0.0] * 8)
    tgraphcanvas.invalidateStaleTP(q)
    assert q.TPalarmtimeindex == 5 and q.afterTP is True
