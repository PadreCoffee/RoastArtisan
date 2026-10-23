"""R2/R3: the outbox must never drop roast data silently.

Before: 5xx / timeouts got 3 attempts ~1 min apart and were then dropped; 409 dropped at once; items older
than 3 days (by modified_at, possibly a file mtime) were dropped with a debug log only; a roast diff for a
roast not known as synced was dropped without a trace. Now transient failures retry with exponential backoff
(up to 24 h per item), age-based discard is off, and every item that finally fails is kept in a dead-letter
file next to the outbox (plus a message to the roaster).
"""

import json
import sys
import types

from PyQt6.QtWidgets import QApplication

try:  # another test module may have replaced QApplication with a mock in sys.modules
    _app = QApplication.instance() or QApplication(sys.argv)
except Exception:  # pylint: disable=broad-except
    _app = None

import artisanlib.main  # noqa: E402,F401
import plus.config as config  # noqa: E402
import plus.queue as q  # noqa: E402


def _r(status):
    return types.SimpleNamespace(status_code=status)


def test_transient_classification() -> None:
    assert q.is_transient_failure(None)                       # no response: timeout / protocol error
    for s in (408, 425, 429, 500, 502, 503, 504):
        assert q.is_transient_failure(_r(s)), s
    for s in (400, 401, 403, 404, 409, 422):
        assert not q.is_transient_failure(_r(s)), s


def test_backoff_grows_and_is_capped() -> None:
    delays = [q.transient_backoff(i) for i in range(12)]
    assert delays[0] == config.queue_retry_delay
    assert delays[1] == 2 * config.queue_retry_delay
    assert all(a <= b for a, b in zip(delays, delays[1:]))
    assert max(delays) == config.queue_transient_max_delay


def test_items_are_never_discarded_by_age() -> None:
    assert config.queue_discard_after == 0
    assert config.queue_transient_give_up >= 24 * 60 * 60


def test_dead_letter_keeps_every_failed_item(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(q, 'queue_path', str(tmp_path))
    msgs: list = []
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
        self.put_back: list = []

    def qsize(self):
        return len(self.items)

    def get(self):
        if not self.items:
            raise _Stop()
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


def _run(monkeypatch, tmp_path, items, responses):
    import plus.queue as qm
    fq = _FakeQueue(items)
    monkeypatch.setattr(qm, 'queue', fq)
    monkeypatch.setattr(qm, 'queue_path', str(tmp_path))
    monkeypatch.setattr(config, 'app_window', types.SimpleNamespace(sendmessage=lambda *a, **k: None,
                                                                    updatePlusStatusSignal=types.SimpleNamespace(emit=lambda: None)))
    sleeps: list = []
    monkeypatch.setattr(qm.time, 'sleep', sleeps.append)
    monkeypatch.setattr(qm.controller, 'connect', lambda **k: None)
    monkeypatch.setattr(qm.controller, 'is_connected', lambda: True)
    monkeypatch.setattr(qm.controller, 'disconnect', lambda **k: None)
    seq = list(responses)
    sent: list = []
    def send(url, data, verb):
        sent.append(data.get('roast_id'))
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
