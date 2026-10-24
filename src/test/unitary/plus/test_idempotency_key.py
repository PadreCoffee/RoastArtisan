"""Every request for one outbox item carries the same Idempotency-Key, also when it is re-sent after a
re-authentication inside sendData()/sendFile(), and new queue items get their key when they are queued."""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication

try:  # another test module may have replaced QApplication with a mock in sys.modules
    _app: object = QApplication.instance() or QApplication(sys.argv)
except Exception:  # pylint: disable=broad-except
    _app = None

import artisanlib.main  # noqa: E402,F401
from plus import connection  # noqa: E402
import plus.queue as q  # noqa: E402


class _Resp:
    def __init__(self, status:int) -> None:
        self.status_code = status
        self.elapsed = type('E', (), {'total_seconds': staticmethod(lambda: 0.1)})()


def _keys(mock_post:Any) -> list[str]:
    return [c.kwargs['headers']['Idempotency-Key'] for c in mock_post.call_args_list]


def test_send_data_keeps_the_key_when_resent_after_reauth() -> None:
    with patch('plus.connection.requests.post', side_effect=[_Resp(401), _Resp(200)]) as post, \
            patch('plus.connection.authentify', return_value=True), patch('plus.connection.time.sleep'):
        connection.sendData('https://x/api/v1/aroast', {'roast_id': 'r1'}, 'POST', idempotency_key='k1')
    assert _keys(post) == ['k1', 'k1']


def test_send_data_without_a_given_key_still_uses_one_key_per_call() -> None:
    with patch('plus.connection.requests.post', side_effect=[_Resp(401), _Resp(200)]) as post, \
            patch('plus.connection.authentify', return_value=True), patch('plus.connection.time.sleep'):
        connection.sendData('https://x/api/v1/aroast', {'roast_id': 'r1'}, 'POST')
    keys = _keys(post)
    assert keys[0] and keys[0] == keys[1]


def test_send_file_sends_the_key_and_keeps_it_after_reauth(tmp_path:Path) -> None:
    f = tmp_path / 'r.alog'
    f.write_text('{}', encoding='utf-8')
    with patch('plus.connection.requests.post', side_effect=[_Resp(401), _Resp(200)]) as post, \
            patch('plus.connection.authentify', return_value=True), patch('plus.connection.time.sleep'):
        connection.sendFile('https://x/api/v1/roasts/r1/upload-profile', str(f), idempotency_key='k2')
    assert _keys(post) == ['k2', 'k2']


class _Q:
    def __init__(self) -> None:
        self.items:list[dict[str, Any]] = []

    def put(self, item:dict[str, Any]) -> None:
        self.items.append(item)


def test_new_profile_upload_item_gets_a_key(tmp_path:Path, monkeypatch:pytest.MonkeyPatch) -> None:
    f = tmp_path / 'r.alog'
    f.write_text('{}', encoding='utf-8')
    fq = _Q()
    monkeypatch.setattr(q, 'queue', fq)
    monkeypatch.setattr(q, 'last_queued_profile_item', None)
    monkeypatch.setattr(q.config, 'profile_upload_enabled', lambda: True)
    assert q.addProfileUpload('8a4b6a7f-3c2d-4e5f-8a9b-0c1d2e3f4a5b', str(f))
    assert len(fq.items[0][q.IDEMPOTENCY_KEY]) == 32
