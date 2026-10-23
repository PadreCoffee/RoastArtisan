"""The "Unsent cloud data" window lists what is still waiting in the outbox queue and what the server
rejected (kept in failed.json and re-sent automatically)."""

import sys
import types
from pathlib import Path

from PyQt6.QtWidgets import QApplication

try:  # another test module may have replaced QApplication with a mock in sys.modules
    _app: object = QApplication.instance() or QApplication(sys.argv)
except Exception:  # pylint: disable=broad-except
    _app = None

import artisanlib.main  # noqa: E402,F401
from plus import config  # noqa: E402
import plus.queue as q  # noqa: E402
from artisanlib import unsent_dialog  # noqa: E402

import pytest  # noqa: E402


def _roast(rid:str, label:str = 'Уганда Элгон') -> dict[str, object]:
    return {'url': config.roast_url, 'verb': 'POST', 'data': {'roast_id': rid, 'date': '2026-10-23T10:00:00.000Z', 'amount': 10.0,
        'label': label, 'batch_prefix': 'R', 'batch_number': 1433, 'modified_at': '2026-10-23T10:05:00.000Z'}}


def test_pending_items_are_read_without_consuming_the_queue(tmp_path:Path, monkeypatch:pytest.MonkeyPatch) -> None:
    persistqueue = pytest.importorskip('persistqueue')
    monkeypatch.setattr(q, 'queue_path', str(tmp_path))
    pq = persistqueue.SQLiteQueue(str(tmp_path), multithreading=True, auto_commit=False)
    pq.put(_roast('r1'))
    pq.put({'url': config.roast_url, 'verb': 'POST', 'data': {'roast_id': 'r1', 'end_weight': 9.0}})
    pq.task_done()
    being_sent = pq.get()          # the worker holds the first item in an open transaction (sending / backing off)
    assert being_sent['data']['roast_id'] == 'r1'
    assert [i['data'].get('label') for i in q.pending_items()] == ['Уганда Элгон', None]   # still listed, nothing consumed
    assert [i['data'].get('label') for i in q.pending_items()] == ['Уганда Элгон', None]
    del pq


def test_rows_show_waiting_and_rejected_items(tmp_path:Path, monkeypatch:pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(q, 'queue_path', str(tmp_path))
    monkeypatch.setattr(config, 'app_window', types.SimpleNamespace(sendmessage=lambda *a, **k: None))
    monkeypatch.setattr(q, 'pending_items', lambda: [_roast('r1')])
    # other test modules may leave a mocked QCoreApplication.translate behind; use the source strings
    monkeypatch.setattr(unsent_dialog, '_tr', lambda _ctx, text: text)
    q.dead_letter({'url': config.roast_url, 'verb': 'POST', 'data': {'roast_id': 'ab12cd34-0000-0000-0000-000000000000', 'end_weight': 9}},
        'http_409', 409)
    q.dead_letter({'url': 'u', 'type': q.PROFILE_UPLOAD_ITEM_TYPE, 'data': {'roast_id': 'r3'}}, 'profile_file_missing')
    rows = unsent_dialog.unsent_rows()
    assert rows[0][:2] == ('Roast', 'R1433 Уганда Элгон') and rows[0][3] == 'Waiting to be sent'
    assert rows[1][0] == 'Roast change' and rows[1][1] == 'ab12cd34' and '409' in rows[1][3]
    assert rows[2][0] == 'Full profile' and 'gone' in rows[2][3]


def test_no_rows_when_everything_is_uploaded(tmp_path:Path, monkeypatch:pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(q, 'queue_path', str(tmp_path))
    assert q.pending_items() == [] and unsent_dialog.unsent_rows() == []
