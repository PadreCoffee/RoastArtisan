"""Regression test: a green weight entered by hand must not be overwritten automatically.

Bug: in Roast Properties the roaster picks coffee + reference and types the batch weight. On OK,
close_OK applies the typed weight and THEN (re)loads the reference as background
(loadbackgroundUUID, force_reload=True). With "Set batch size from background" ticked,
loadbackground() then replaced the typed weight with the reference's batch weight — on every OK,
including the dialog auto-opened at DROP, so the wrong weight was also uploaded. The scheduler's
set_roast_properties likewise overwrote the weight unconditionally.

Fix: qmc.weight_manually_set — set on OK only when the roaster edited the weight-in field (typed or
took it from the scale); while set, neither the background load nor the scheduler touch the weight.
Cleared when the roast properties are reset (new roast) and on OFF.
"""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from artisanlib.main import ApplicationWindow  # noqa: E402
from artisanlib.roast_properties import editGraphDlg  # noqa: E402
from plus.schedule import ScheduleWindow  # noqa: E402


def _aw(manual: bool, flag: bool = True, flagon: bool = True, cur_file: str|None = None, schedule_window: object = None):
    o = types.SimpleNamespace()
    o.qmc = types.SimpleNamespace(setBatchSizeFromBackground=flag, flagon=flagon, weight_manually_set=manual)
    o.curFile = cur_file
    o.schedule_window = schedule_window
    return o


def test_background_batch_size_applies_when_weight_not_set_by_hand() -> None:
    assert ApplicationWindow.batchSizeFromBackgroundAllowed(_aw(manual=False)) is True


def test_background_batch_size_never_overwrites_a_manual_weight() -> None:
    assert ApplicationWindow.batchSizeFromBackgroundAllowed(_aw(manual=True)) is False


def test_background_batch_size_existing_gates_kept() -> None:
    assert ApplicationWindow.batchSizeFromBackgroundAllowed(_aw(manual=False, flag=False)) is False
    assert ApplicationWindow.batchSizeFromBackgroundAllowed(_aw(manual=False, schedule_window=object())) is False
    # not sampling and a foreground profile is loaded -> do not touch its weight
    assert ApplicationWindow.batchSizeFromBackgroundAllowed(_aw(manual=False, flagon=False, cur_file='x.alog')) is False


def test_typing_into_weight_in_marks_it_user_edited() -> None:
    o = types.SimpleNamespace(weight_in_user_edited=False)
    editGraphDlg.weightInTextEdited(o, '12.5')
    assert o.weight_in_user_edited is True


def _sched(manual: bool):
    qmc = types.SimpleNamespace(weight=(11.0, 0, 'Kg'), weight_manually_set=manual)
    return types.SimpleNamespace(aw=types.SimpleNamespace(qmc=qmc))


def test_schedule_item_weight_applies_when_not_set_by_hand() -> None:
    s = _sched(manual=False)
    ScheduleWindow.apply_schedule_item_weight(s, 9.0, 1)   # 9 kg, unit idx 1 = Kg
    assert s.aw.qmc.weight[0] == 9.0


def test_schedule_item_weight_never_overwrites_a_manual_weight() -> None:
    s = _sched(manual=True)
    ScheduleWindow.apply_schedule_item_weight(s, 9.0, 1)
    assert s.aw.qmc.weight[0] == 11.0
