"""R5 / R6 / missing comma / send-log: small silent data-loss fixes."""

import sys
import types

from PyQt6.QtWidgets import QApplication

try:  # another test module may have replaced QApplication with a mock in sys.modules
    _app = QApplication.instance() or QApplication(sys.argv)
except Exception:  # pylint: disable=broad-except
    _app = None

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


def test_schedule_cache_save_keeps_other_accounts(tmp_path) -> None:
    # R8: save_completed/save_prepared opened the file with 'w'/'w+' and then read it (always empty), so each
    # save wiped every other account's cached data
    import json
    import plus.schedule as sch
    p = tmp_path / 'completed.json'
    p.write_text(json.dumps({'accA': [1, 2], 'accB': [3]}), encoding='utf-8')
    sch._save_account_cache(str(p), 'accA', [9])
    assert json.loads(p.read_text(encoding='utf-8')) == {'accA': [9], 'accB': [3]}
    sch._save_account_cache(str(tmp_path / 'new.json'), 'accC', {'x': 1})      # missing file is created
    assert json.loads((tmp_path / 'new.json').read_text(encoding='utf-8')) == {'accC': {'x': 1}}
    assert not any(f.name.endswith('.tmp') for f in tmp_path.iterdir())


def test_switch_operator_rederives_server_urls(monkeypatch) -> None:
    import plus.config as config
    import plus.connection as connection
    import plus.controller as controller
    monkeypatch.setattr(connection, 'clearCredentials', lambda **k: None)
    monkeypatch.setattr(connection, 'authentify', lambda: False)
    aw = types.SimpleNamespace(plus_server_url=None, plus_account=None, plus_email=None,
                               sendmessage=lambda *a, **k: None, updatePlusStatusSignal=types.SimpleNamespace(emit=lambda: None))
    monkeypatch.setattr(config, 'app_window', aw)
    seen: list = []
    monkeypatch.setattr(config, 'set_server_base_url', lambda url: seen.append(url))
    controller.switchOperator('b@example.com', 'https://other.example')
    assert seen == ['https://other.example']


def _reset_cache():
    sync.cached_sync_record = None
    sync.cached_sync_record_hash = None


def test_cache_after_full_upload_is_what_was_sent_so_later_edits_still_sync() -> None:
    # R4: the server state was taken from the LIVE properties after the upload; an edit made between queueing
    # and upload then looked already synced and was never sent
    _reset_cache()
    sent = sync.suppress_zero_values({'roast_id': 'r1', 'amount': 10.0, 'end_weight': 8.4, 'whole_color': 0,
                                      'cupping_score': 50, 'date': 'd'})
    sync.setSyncRecordFromSent(sent, full_record=True)
    unchanged = {'roast_id': 'r1', 'amount': 10.0, 'end_weight': 8.4, 'whole_color': 0, 'cupping_score': 50}
    assert sync.syncRecordUpdated(unchanged) is False          # suppressed 0/50 hash like the live record
    edited = dict(unchanged, end_weight=8.6)                    # changed after the item was queued
    assert sync.syncRecordUpdated(edited) is True
    assert sync.diffCachedSyncRecord(edited).get('end_weight') == 8.6


def test_cache_after_diff_upload_merges_into_previous_record() -> None:
    _reset_cache()
    sync.setSyncRecordFromSent({'roast_id': 'r1', 'amount': 10.0, 'end_weight': 8.4, 'date': 'd'}, full_record=True)
    sync.setSyncRecordFromSent({'roast_id': 'r1', 'end_weight': 8.5}, full_record=False)
    assert sync.cached_sync_record['amount'] == 10.0 and sync.cached_sync_record['end_weight'] == 8.5
    _reset_cache()
