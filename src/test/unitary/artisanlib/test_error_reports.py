"""Crash and error reports to the Roastlocal cloud (POST /api/v1/client/reports): scrubbing, grouping,
rate limits, the local outbox and the sender's handling of the cloud's answers."""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtWidgets import QApplication

try:  # another test module may have replaced QApplication with a mock in sys.modules
    _app: object = QApplication.instance() or QApplication(sys.argv)
except Exception:  # pylint: disable=broad-except
    _app = None

from artisanlib import error_reports as er  # noqa: E402


@pytest.fixture
def outbox(tmp_path:Path, monkeypatch:pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(er, 'outbox_dir', lambda: str(tmp_path))
    monkeypatch.setattr(er, 'enabled', lambda: True)
    monkeypatch.setattr(er, '_logged_in', lambda: True)
    monkeypatch.setattr(er, 'log_tail', lambda: '')
    monkeypatch.setattr(er, '_recent', {})
    monkeypatch.setattr(er._wakeup, 'set', lambda: None) # pylint: disable=protected-access
    return tmp_path


def _boom() -> None:
    raise ZeroDivisionError('float division by zero')


def _crash() -> bool:
    try:
        _boom()
    except ZeroDivisionError:
        exc_type, exc_value, tb = sys.exc_info()
        assert exc_type is not None and exc_value is not None
        return er.report_exception(exc_type, exc_value, tb)
    return False


def _reports(d:Path) -> list[dict[str, Any]]:
    return [json.loads(Path(p).read_text(encoding='utf-8')) for p in er.pending_files(str(d))]


def test_scrub_removes_secrets_and_personal_data() -> None:
    home = os.path.expanduser('~')
    s = er.scrub(f"Authorization: Bearer abc.def.ghi token='t0k3n' {{'password': \"hunter2\"}} mail igor@example.com "
                 f'GET https://roastlocal.ru/api/v1/aroast?token=x&id=5 file {home}/Documents/R1433.alog')
    assert 'abc.def.ghi' not in s and 't0k3n' not in s and 'hunter2' not in s and 'igor@example.com' not in s
    assert '<email>' in s and 'https://roastlocal.ru/api/v1/aroast ' in s and 'token=x' not in s
    assert '~/Documents/R1433.alog' in s


def test_crash_report_content(outbox:Path) -> None:
    assert _crash()
    [r] = _reports(outbox)
    assert r['schema'] == 1 and r['kind'] == 'crash' and r['occurrences'] == 1
    assert r['error']['type'] == 'ZeroDivisionError' and 'float division by zero' in r['error']['message']
    assert 'test_error_reports.py' in r['error']['line'] and 'Traceback' in r['error']['traceback']
    assert len(r['fingerprint']) == 40 and r['client_report_id'] and r['occurred_at'].endswith('Z')
    assert r['app']['version'] and r['platform']['os']
    assert 'last_login' not in r                       # logged in: the cloud takes the account from the token


def test_identical_crash_is_counted_not_queued_twice(outbox:Path) -> None:
    assert _crash()
    assert not _crash()
    [r] = _reports(outbox)
    assert r['occurrences'] == 1                       # counted in memory, written at most once a minute
    er._flush_occurrences(r['fingerprint'], er._recent[r['fingerprint']]) # pylint: disable=protected-access
    assert _reports(outbox)[0]['occurrences'] == 2


def test_errors_are_grouped_by_text_without_numbers(outbox:Path) -> None:
    assert er.report_error('Serial Exception: COM3 timeout after 1.2s')
    assert not er.report_error('Serial Exception: COM3 timeout after 3.4s')
    assert er.report_error('IO Error: export failed')
    assert [r['kind'] for r in _reports(outbox)] == ['error', 'error']


def test_daily_cap(outbox:Path) -> None:
    for i in range(er.MAX_PER_DAY + 5):
        er.report_error(f'distinct error {chr(65 + i % 26)}{chr(65 + i // 26)}')
    assert len(_reports(outbox)) == er.MAX_PER_DAY


def test_last_login_sent_only_when_logged_out(outbox:Path, monkeypatch:pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(er, '_logged_in', lambda: False)
    er.remember_login('igor@example.com', 'S.Pudra')
    assert _crash()
    [r] = _reports(outbox)
    assert r['last_login'] == {'login': 'igor@example.com', 'org_hint': 'S.Pudra'}  # not scrubbed (cloud requirement)


def test_disabled_reports_nothing(outbox:Path, monkeypatch:pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(er, 'enabled', lambda: False)
    assert not _crash() and not er.report_error('x')
    assert _reports(outbox) == []


@pytest.mark.parametrize(('status', 'kept'), [(202, False), (422, False), (413, False),
    (404, True), (429, True), (500, True), (None, True)])
def test_sender_keeps_report_until_stored(outbox:Path, monkeypatch:pytest.MonkeyPatch, status:int|None, kept:bool) -> None:
    assert _crash()
    monkeypatch.setattr(er, '_post', lambda report, authorized: status)
    assert er.send_pending() is (not kept)
    assert bool(_reports(outbox)) is kept


def test_sender_retries_expired_session_anonymously(outbox:Path, monkeypatch:pytest.MonkeyPatch) -> None:
    er.remember_login('igor@example.com', '')
    assert _crash()
    calls:list[tuple[bool, bool]] = []
    def post(report:dict[str, Any], authorized:bool) -> int:
        calls.append((authorized, 'last_login' in report))
        return 401 if authorized else 202
    monkeypatch.setattr(er, '_post', post)
    assert er.send_pending()
    assert calls == [(True, False), (False, True)] and _reports(outbox) == []


def test_reports_url_points_to_the_cloud() -> None:
    assert er.reports_url().endswith('/api/v1/client/reports')
