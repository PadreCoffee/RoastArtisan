"""Regression test: OFF must push the roast's final state to the cloud even if autosave did not save.

Bug: the cloud sync on OFF (updateSyncRecordHashAndSync -> /aroast diff incl. weight + profile
re-upload) ran only inside a successful automaticsave(). With autosave disabled, or an autosave path
that does not exist on this machine (e.g. a Windows path in settings copied to a Mac), nothing was
synced on OFF, so a weight or other change made after DROP never reached the cloud.

Fix: after the OFF autosave attempt, if the roast was not written to a new file (curFile unchanged),
sync it to the cloud directly.
"""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401
import plus.controller  # noqa: E402
from artisanlib.canvas import tgraphcanvas  # noqa: E402


def _q(cur_file):
    return types.SimpleNamespace(aw=types.SimpleNamespace(curFile=cur_file))


def _calls(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(plus.controller, 'updateSyncRecordHashAndSync', lambda: calls.append(True))
    return calls


def test_syncs_when_autosave_wrote_nothing(monkeypatch) -> None:
    calls = _calls(monkeypatch)
    tgraphcanvas.syncRoastToCloudIfNotAutosaved(_q(None), None)          # autosave failed / disabled
    assert calls == [True]


def test_syncs_when_curfile_unchanged(monkeypatch) -> None:
    calls = _calls(monkeypatch)
    tgraphcanvas.syncRoastToCloudIfNotAutosaved(_q('/old.alog'), '/old.alog')
    assert calls == [True]


def test_no_double_sync_when_autosave_saved(monkeypatch) -> None:
    calls = _calls(monkeypatch)
    # automaticsave() wrote a new file and already synced inside
    tgraphcanvas.syncRoastToCloudIfNotAutosaved(_q('/new.alog'), '/old.alog')
    assert calls == []
