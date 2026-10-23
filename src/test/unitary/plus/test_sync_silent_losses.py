"""R5 / R6 / missing comma / send-log: small silent data-loss fixes."""

import sys
import types

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import artisanlib.main  # noqa: E402,F401
import plus.roast as roast  # noqa: E402
import plus.sync as sync  # noqa: E402


def _tmp_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(sync, 'getSyncPath', lambda lock=False: str(tmp_path / ('sync_lock' if lock else 'sync')))


def test_server_iso_modified_at_is_stored_as_epoch_and_readable(monkeypatch, tmp_path) -> None:
    # R5: an applied server update hands addSync the server's ISO string; it used to be stored as-is and
    # getSync() then failed on float() -> the roast silently counted as unsynced
    _tmp_sync(monkeypatch, tmp_path)
    sync.addSync('0123456789abcdef0123456789abcdef', '2026-10-23T10:00:00.000Z')
    ts = sync.getSync('0123456789abcdef0123456789abcdef')
    assert isinstance(ts, float) and ts > 1.7e9


def test_legacy_string_value_in_cache_is_tolerated(monkeypatch, tmp_path) -> None:
    import shelve
    _tmp_sync(monkeypatch, tmp_path)
    with shelve.open(str(tmp_path / 'sync')) as db:
        db['0123456789abcdef0123456789abcdef'] = '2026-10-23T10:00:00.000Z'   # written by an older client
    assert isinstance(sync.getSync('0123456789abcdef0123456789abcdef'), float)


def test_roasterheating_and_btu_elec_are_separate_attributes() -> None:
    # a missing comma concatenated them to 'roasterheatingBTU_ELEC', so neither reached the cloud diffs
    lists = [roast.sync_record_zero_supressed_attributes_unsynced, roast.sync_record_zero_supressed_attributes_synced]
    flat = [a for lst in lists for a in lst]
    assert 'roasterheatingBTU_ELEC' not in flat
    assert 'roasterheating' in flat and 'BTU_ELEC' in flat


def test_missing_sync_record_never_sends_the_estimate_to_the_cloud(monkeypatch) -> None:
    # R6: an item without sync record is marked measured locally only; the estimate is never POSTed as end_weight
    import plus.connection
    import plus.schedule as sch
    sent: list = []
    monkeypatch.setattr(plus.connection, 'sendData', lambda *a, **k: sent.append(a))
    monkeypatch.setattr(sch, 'add_completed', lambda *a, **k: None)
    updates: list = []
    item = types.SimpleNamespace(roastUUID=types.SimpleNamespace(hex='abc'), measured=False,
                                 update_completed_item=lambda aw, ch: updates.append(ch),
                                 model_dump=lambda mode: {'prefix': 'x'})
    w = types.SimpleNamespace(completed_items=[item], aw=types.SimpleNamespace(plus_account_id='acc'),
                              updateRoastedItems=lambda: None, set_next=lambda *a: None)
    sch.ScheduleWindow.mark_roasted_weight_locally(w, 'abc', 11.5)
    assert sent == [] and item.measured is True and updates[0]['end_weight'] == 11.5


def test_send_log_is_disabled(monkeypatch) -> None:
    from artisanlib.main import ApplicationWindow
    msgs: list = []
    aw = types.SimpleNamespace(sendmessage=msgs.append)
    ApplicationWindow.sendLog(aw)   # must not compose / open any e-mail
    assert msgs and 'disabled' in str(msgs[0]).lower()
