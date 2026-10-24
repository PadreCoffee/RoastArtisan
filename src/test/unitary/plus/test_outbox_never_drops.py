"""R2/R3: the outbox must never drop roast data silently.

Before: 5xx / timeouts got 3 attempts ~1 min apart and were then dropped; 409 dropped at once; items older
than 3 days (by modified_at, possibly a file mtime) were dropped with a debug log only; a roast diff for a
roast not known as synced was dropped without a trace. Now transient failures retry with exponential backoff
(up to 24 h per item), age-based discard is off, and every item that finally fails is kept in a dead-letter
file next to the outbox (plus a message to the roaster).
"""

import json
import sys
from typing import Any
import types

from PyQt6.QtWidgets import QApplication

try:  # another test module may have replaced QApplication with a mock in sys.modules
    _app: object = QApplication.instance() or QApplication(sys.argv)
except Exception:  # pylint: disable=broad-except
    _app = None

import artisanlib.main  # noqa: E402,F401
from plus import config  # noqa: E402
import plus.queue as q  # noqa: E402


def _r(status):
    return types.SimpleNamespace(status_code=status)


def test_transient_classification() -> None:
    assert q.is_transient_failure(None)                       # no response: timeout / protocol error
    for s in (401, 408, 425, 429, 500, 502, 503, 504):     # 401: expired session, re-authenticated on retry
        assert q.is_transient_failure(_r(s)), s
    for s in (400, 403, 404, 409, 422):
        assert not q.is_transient_failure(_r(s)), s


def test_backoff_grows_and_is_capped() -> None:
    delays = [q.transient_backoff(i) for i in range(12)]
    assert delays[0] == config.queue_retry_delay
    assert delays[1] == 2 * config.queue_retry_delay
    assert all(a <= b for a, b in zip(delays, delays[1:], strict=False))
    assert max(delays) == config.queue_transient_max_delay


def test_items_are_never_discarded_by_age() -> None:
    assert config.queue_discard_after == 0
    assert not hasattr(config, 'queue_transient_give_up')   # transient failures are never given up


def test_dead_letter_keeps_every_failed_item(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(q, 'queue_path', str(tmp_path))
    msgs: list[Any] = []
    monkeypatch.setattr(config, 'app_window', types.SimpleNamespace(sendmessage=lambda m, *a, **k: msgs.append(m)))
    item1 = {'url': 'u', 'verb': 'POST', 'data': {'roast_id': 'r1', 'modified_at': '2026-10-23T10:00:00.000Z'}}
    item2 = {'url': 'u', 'verb': 'POST', 'data': {'roast_id': 'r2'}}
    q.dead_letter(item1, 'http_409', 409)
    q.dead_letter(item2, 'not_synced')
    entries = json.loads((tmp_path / q.DEAD_LETTER_FILE).read_text(encoding='utf-8'))
    assert [e['item']['data']['roast_id'] for e in entries] == ['r1', 'r2']
    assert entries[0]['reason'] == 'http_409' and entries[0]['status'] == 409
    assert len(msgs) == 2


def test_unreadable_dead_letter_file_is_kept_aside_not_overwritten(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(q, 'queue_path', str(tmp_path))
    monkeypatch.setattr(config, 'app_window', None)
    (tmp_path / q.DEAD_LETTER_FILE).write_text('{not json', encoding='utf-8')
    q.dead_letter({'data': {'roast_id': 'r3'}}, 'http_500', 500)
    assert any(p.name.endswith('.corrupt') for p in tmp_path.iterdir())
    entries = json.loads((tmp_path / q.DEAD_LETTER_FILE).read_text(encoding='utf-8'))
    assert entries[0]['item']['data']['roast_id'] == 'r3'


# --- the real worker loop (Worker.task) driven with a fake queue / transport ---

class _Stop(BaseException):  # not caught by the loop's `except Exception`
    pass


class _FakeQueue:
    def __init__(self, items):
        self.items = list(items)
        self.done = 0
        self.put_back: list[Any] = []

    def qsize(self):
        return len(self.items)

    def get(self):
        if not self.items:
            raise _Stop
        return self.items.pop(0)

    def task_done(self):
        self.done += 1

    def put(self, item):
        self.put_back.append(item)


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.headers = {'content-type': 'application/json'}
        self.text = ''

    def json(self):
        return {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


_KEYS: list[Any] = []   # idempotency keys sent by the last _run, in order


def _run(monkeypatch, tmp_path, items, responses):
    import plus.queue as qm
    fq = _FakeQueue(items)
    monkeypatch.setattr(qm, 'queue', fq)
    monkeypatch.setattr(qm, 'queue_path', str(tmp_path))
    monkeypatch.setattr(config, 'app_window', types.SimpleNamespace(sendmessage=lambda *a, **k: None,
                                                                    updatePlusStatusSignal=types.SimpleNamespace(emit=lambda: None)))
    sleeps: list[Any] = []
    monkeypatch.setattr(qm.time, 'sleep', sleeps.append)
    monkeypatch.setattr(qm.controller, 'connect', lambda **k: None)
    monkeypatch.setattr(qm.controller, 'is_connected', lambda: True)
    monkeypatch.setattr(qm.controller, 'disconnect', lambda **k: None)
    seq = list(responses)
    sent: list[Any] = []
    keys = _KEYS
    keys.clear()
    def send(url, data, verb, idempotency_key=None):
        sent.append(data.get('roast_id'))
        keys.append(idempotency_key)
        return _Resp(seq.pop(0))
    monkeypatch.setattr(qm.connection, 'sendData', send)
    monkeypatch.setattr(qm.Worker, 'addSyncItem', staticmethod(lambda item: None))
    monkeypatch.setattr(qm.roast, 'getSyncRecord', lambda *a: ({'roast_id': 'other'}, 'h'))
    monkeypatch.setattr(config, 'profile_upload_enabled', lambda: False)
    monkeypatch.setattr(qm.sync, 'getSync', lambda rid: None)
    w = qm.Worker()
    try:
        w.task()
    except _Stop:
        pass
    dl = tmp_path / qm.DEAD_LETTER_FILE
    return fq, sent, sleeps, (json.loads(dl.read_text(encoding='utf-8')) if dl.exists() else [])


def _full(rid):
    return {'url': config.roast_url, 'verb': 'POST',
            'data': {'roast_id': rid, 'date': '2026-10-23T10:00:00.000Z', 'amount': 10.0,
                     'modified_at': '2020-01-01T00:00:00.000Z'}}   # very old: must NOT be discarded by age


def test_loop_retries_transient_5xx_until_delivered(monkeypatch, tmp_path) -> None:
    fq, sent, sleeps, dead = _run(monkeypatch, tmp_path, [_full('r1')], [503, 502, 500, 504, 200])
    assert sent == ['r1'] * 5 and dead == [] and fq.done == 1      # 4 transient failures, then delivered
    assert max(sleeps) <= config.queue_transient_max_delay


def test_loop_keeps_rejected_save_in_dead_letter(monkeypatch, tmp_path) -> None:
    fq, sent, _, dead = _run(monkeypatch, tmp_path, [_full('r1'), _full('r2')], [409, 200])
    assert sent == ['r1', 'r2'] and fq.done == 2                   # the 409 does not block the next roast
    assert [d['item']['data']['roast_id'] for d in dead] == ['r1'] and dead[0]['status'] == 409


def test_loop_keeps_diff_of_unsynced_roast_instead_of_dropping(monkeypatch, tmp_path) -> None:
    diff = {'url': config.roast_url, 'verb': 'POST', 'data': {'roast_id': 'r9', 'end_weight': 9.1,
                                                              'modified_at': '2026-10-23T10:00:00.000Z'}}
    fq, sent, _, dead = _run(monkeypatch, tmp_path, [diff], [])
    assert sent == [] and fq.done == 1
    assert dead[0]['reason'] == 'not_synced' and dead[0]['item']['data']['end_weight'] == 9.1


def test_loop_retries_expired_session_until_delivered(monkeypatch, tmp_path) -> None:
    # 401 used to burn the retries and end in the dead-letter file; now it re-authenticates and retries
    fq, sent, _, dead = _run(monkeypatch, tmp_path, [_full('r1')], [401, 401, 401, 401, 200])
    assert sent == ['r1'] * 5 and dead == [] and fq.done == 1


def test_loop_moves_long_failing_item_to_the_end_instead_of_giving_up(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, 'queue_transient_rotate_after', 0)
    fq, sent, _, dead = _run(monkeypatch, tmp_path, [_full('r1'), _full('r2')], [503, 200])
    assert sent == ['r1', 'r2'] and dead == []                     # r1 does not block r2 ..
    assert [i['data']['roast_id'] for i in fq.put_back] == ['r1']  # .. and is kept for another try


def test_dead_letters_are_requeued_until_sent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(q, 'queue_path', str(tmp_path))
    msgs: list[Any] = []
    monkeypatch.setattr(config, 'app_window', types.SimpleNamespace(sendmessage=lambda m, *a, **k: msgs.append(m)))
    fq = _FakeQueue([])
    monkeypatch.setattr(q, 'queue', fq)
    q.dead_letter(_full('r1'), 'http_409', 409)
    q.dead_letter({'url': 'u', 'type': 'profile_upload', 'data': {'roast_id': 'r2'}}, 'profile_file_missing')
    assert q.requeue_dead_letters() == 1
    assert [i['data']['roast_id'] for i in fq.put_back] == ['r1'] and fq.put_back[0][q.DEAD_LETTER_RETRIES_KEY] == 1
    left = json.loads((tmp_path / q.DEAD_LETTER_FILE).read_text(encoding='utf-8'))
    assert [e['reason'] for e in left] == ['profile_file_missing']   # a missing file can never be sent
    # rejected again after the automatic re-send: kept again, without notifying the roaster a second time
    q.dead_letter(fq.put_back[0], 'http_409', 409)
    assert len(msgs) == 2
    assert q.requeue_dead_letters() == 1 and fq.put_back[1][q.DEAD_LETTER_RETRIES_KEY] == 2


def test_requeue_without_dead_letters_is_a_no_op(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(q, 'queue_path', str(tmp_path))
    monkeypatch.setattr(q, 'queue', _FakeQueue([]))
    assert q.requeue_dead_letters() == 0
    assert not (tmp_path / q.DEAD_LETTER_FILE).exists()


def test_retries_of_one_item_reuse_its_idempotency_key(monkeypatch, tmp_path) -> None:
    # a new key per attempt made every retry look like a new request to the cloud
    item = _full('r1')
    item[q.IDEMPOTENCY_KEY] = 'k-r1'
    fq, sent, _, _ = _run(monkeypatch, tmp_path, [item], [503, 401, 500, 200])
    assert sent == ['r1'] * 4 and _KEYS == ['k-r1'] * 4 and fq.done == 1


def test_item_from_an_older_version_gets_one_key_for_all_attempts(monkeypatch, tmp_path) -> None:
    fq, _, _, _ = _run(monkeypatch, tmp_path, [_full('r1')], [503, 200])   # queued without a key
    assert _KEYS[0] and _KEYS[0] == _KEYS[1] and fq.done == 1


def test_rotated_and_dead_letter_items_keep_their_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, 'queue_transient_rotate_after', 0)
    item = _full('r1')
    item[q.IDEMPOTENCY_KEY] = 'k-r1'
    fq, _, _, _ = _run(monkeypatch, tmp_path, [item], [503])
    assert fq.put_back[0][q.IDEMPOTENCY_KEY] == 'k-r1'                     # moved to the end of the queue
    monkeypatch.setattr(config, 'app_window', None)
    q.dead_letter(fq.put_back[0], 'http_409', 409)
    fq2 = _FakeQueue([])
    monkeypatch.setattr(q, 'queue', fq2)
    assert q.requeue_dead_letters() == 1 and fq2.put_back[0][q.IDEMPOTENCY_KEY] == 'k-r1'   # re-sent from failed.json
