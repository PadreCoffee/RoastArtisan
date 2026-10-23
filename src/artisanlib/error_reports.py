#
# ABOUT
# Crash and error reports to the Roastlocal cloud (POST {api}/client/reports, contract agreed with the cloud
# 2026-10-23, see docs/handoff/crash-reports-cloud-spec.md and the cloud's answer).
#
# A report is written to a small local outbox (one JSON file per report, next to the roast outbox) and sent by a
# background thread until the cloud stores it (202). The same client_report_id is reused on every attempt, so the
# endpoint can deduplicate. Nothing here may ever raise into the caller: reporting must not break the app.

import os
import re
import sys
import json
import time
import uuid
import hashlib
import logging
import threading
import traceback
from typing import Final, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType # pylint: disable=unused-import
    from artisanlib.main import ApplicationWindow # pylint: disable=unused-import

_log: Final[logging.Logger] = logging.getLogger(__name__)

SCHEMA: Final[int] = 1
OUTBOX_DIR: Final[str] = 'error_reports'
STATE_FILE: Final[str] = 'state.json'
SETTINGS_KEY: Final[str] = 'sendErrorReports'
LAST_LOGIN_FILE: Final[str] = 'last_login.json'

MAX_TRACEBACK: Final[int] = 64 * 1024
MAX_LOG_TAIL: Final[int] = 128 * 1024
LOG_TAIL_LINES: Final[int] = 300
MAX_PER_DAY: Final[int] = 20            # reports queued per installation and day
SAME_FINGERPRINT_INTERVAL: Final[int] = 60 * 60   # an identical report is queued at most once per hour (then counted)
SEND_INTERVAL: Final[int] = 60          # seconds between outbox scans while all is well
MAX_BACKOFF: Final[int] = 15 * 60

_lock = threading.RLock()
# fingerprint -> [queued_at, client_report_id, occurrences not yet written, last write]: repeated errors (a failing
# device may log one per sample) are counted in memory and written to the queued report at most once a minute
_recent:dict[str, list[Any]] = {}
_aw:'ApplicationWindow|None' = None
_sender:threading.Thread|None = None
_wakeup = threading.Event()


# --- settings ---

def enabled() -> bool:
    try:
        from PyQt6.QtCore import QSettings
        from artisanlib.util import toBool
        settings = QSettings()
        return toBool(settings.value(SETTINGS_KEY, True)) if settings.contains(SETTINGS_KEY) else True
    except Exception:  # pylint: disable=broad-except
        return True


def set_enabled(on:bool) -> None:
    try:
        from PyQt6.QtCore import QSettings
        QSettings().setValue(SETTINGS_KEY, bool(on))
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)


# remembers the account of the last successful cloud login, sent (untrusted, display only) with reports made while
# nobody is logged in, so the owner can see which roastery a pre-login crash comes from
def remember_login(login:str|None, org_hint:str|None) -> None:
    if not login:
        return
    try:
        _write_json(os.path.join(outbox_dir(), LAST_LOGIN_FILE), {'login': login, 'org_hint': org_hint or ''})
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)


def _last_login() -> dict[str, str]|None:
    try:
        with open(os.path.join(outbox_dir(), LAST_LOGIN_FILE), encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get('login'):
            return {'login': str(d['login']), 'org_hint': str(d.get('org_hint') or '')}
    except Exception:  # pylint: disable=broad-except
        pass
    return None


# --- scrubbing ---

_HOME: Final[str] = os.path.expanduser('~')
_RE_BEARER = re.compile(r'(Bearer\s+)\S+', re.IGNORECASE)
_RE_SECRET_KV = re.compile(r"""(['"]?(?:token|passwd|password|pass|secret|authorization|api_key|apikey)['"]?\s*[:=]\s*)(['"]?)[^\s'",}]+\2""", re.IGNORECASE)
_RE_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
_RE_URL_QUERY = re.compile(r'(\bhttps?://[^\s?#\'"<>]+)[?#][^\s\'"<>]*', re.IGNORECASE)


def scrub(text:str) -> str:
    """Removes secrets and personal data from text sent to the cloud (tokens, passwords, e-mails, home path,
    URL query strings)."""
    s = _RE_URL_QUERY.sub(r'\1', text) # first: a query string may carry a token=...
    s = _RE_BEARER.sub(r'\1<token>', s)
    s = _RE_SECRET_KV.sub(r'\1<secret>', s)
    s = _RE_EMAIL.sub('<email>', s)
    if len(_HOME) > 1:
        s = s.replace(_HOME, '~')
    return s


def _truncate(text:str, limit:int, keep_end:bool) -> str:
    data = text.encode('utf-8')
    if len(data) <= limit:
        return text
    cut = data[-limit:] if keep_end else data[:limit]
    return cut.decode('utf-8', errors='ignore')


# --- report content ---

def fingerprint(exc_type:str, frames:list[tuple[str, str]]) -> str:
    """Groups identical failures: exception type + innermost 5 frames (file name, function), no line numbers."""
    key = exc_type + '|' + '|'.join(f'{os.path.basename(f)}:{fn}' for f, fn in frames[-5:])
    return hashlib.sha1(key.encode('utf-8'), usedforsecurity=False).hexdigest()


def _log_file() -> str|None:
    for h in logging.getLogger().handlers:
        name = getattr(h, 'baseFilename', None)
        if isinstance(name, str) and os.path.exists(name):
            return name
    return None


def log_tail() -> str:
    path = _log_file()
    if path is None:
        return ''
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4 * MAX_LOG_TAIL))
            lines = f.read().decode('utf-8', errors='replace').splitlines()[-LOG_TAIL_LINES:]
        return _truncate(scrub('\n'.join(lines)), MAX_LOG_TAIL, keep_end=True)
    except Exception:  # pylint: disable=broad-except
        return ''


def _app_info() -> dict[str, Any]:
    from artisanlib import __version__, __revision__, __build__
    return {'version': __version__, 'revision': __revision__, 'build': __build__, 'frozen': bool(getattr(sys, 'frozen', False))}


def _platform_info(aw:'ApplicationWindow|None') -> dict[str, Any]:
    import platform
    from PyQt6.QtCore import qVersion
    res:dict[str, Any] = {'os': platform.system(), 'os_version': platform.release(), 'arch': platform.machine(),
        'python': platform.python_version(), 'qt': qVersion()}
    try:
        if aw is not None:
            os_name, os_version, os_arch = aw.get_os()
            res.update({'os': os_name, 'os_version': os_version, 'arch': os_arch})
            res['locale'] = str(aw.locale_str)
    except Exception:  # pylint: disable=broad-except
        pass
    return res


def _roast_phase(qmc:Any) -> str:
    ti = list(getattr(qmc, 'timeindex', []))
    if len(ti) < 7:
        return ''
    if ti[6] > 0:
        return 'after DROP'
    if ti[2] > 0:
        return 'after FCs'
    if ti[1] > 0:
        return 'after DRY'
    if ti[0] > -1:
        return 'after CHARGE'
    return 'before CHARGE'


def _context(aw:'ApplicationWindow|None') -> dict[str, Any]:
    res:dict[str, Any] = {}
    if aw is None:
        return res
    try:
        qmc = aw.qmc
        if qmc.roastertype_setup:
            res['machine'] = scrub(str(qmc.roastertype_setup))
        if 0 < qmc.device <= len(qmc.devices):
            res['device'] = qmc.devices[qmc.device - 1]
        res['sampling'] = bool(qmc.flagstart)
        if qmc.flagstart:
            res['roast_phase'] = _roast_phase(qmc)
        res['ui_mode'] = str(getattr(aw.ui_mode, 'name', aw.ui_mode)).lower()
    except Exception:  # pylint: disable=broad-except
        pass
    return res


def _logged_in() -> bool:
    try:
        from plus import connection
        return connection.getToken() is not None
    except Exception:  # pylint: disable=broad-except
        return False


def build_report(kind:str, exc_type:str, message:str, tb_text:str, line:str, frames:list[tuple[str, str]],
        aw:'ApplicationWindow|None' = None) -> dict[str, Any]:
    report:dict[str, Any] = {
        'schema': SCHEMA,
        'kind': kind,
        'client_report_id': str(uuid.uuid4()),
        'occurred_at': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + f'.{int(time.time() * 1000) % 1000:03d}Z',
        'fingerprint': fingerprint(exc_type, frames),
        'app': _app_info(),
        'platform': _platform_info(aw),
        'context': _context(aw),
        'error': {'type': exc_type, 'message': _truncate(scrub(message), 4096, keep_end=False),
                  'traceback': _truncate(scrub(tb_text), MAX_TRACEBACK, keep_end=True), 'line': line},
        'log_tail': log_tail(),
        'occurrences': 1,
    }
    if not _logged_in():
        last = _last_login()
        if last is not None:
            report['last_login'] = last # the one place the login e-mail is not scrubbed (cloud requirement)
    return report


# --- local outbox ---

def outbox_dir() -> str:
    from artisanlib.util import getDirectory
    path = getDirectory(OUTBOX_DIR, share=False)
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path:str, data:Any) -> None:
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, default=str) # never fail on an odd value
    os.replace(tmp, path)


def _load_state(d:str) -> dict[str, Any]:
    try:
        with open(os.path.join(d, STATE_FILE), encoding='utf-8') as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except Exception:  # pylint: disable=broad-except
        return {}


def pending_files(d:str|None = None) -> list[str]:
    d = d or outbox_dir()
    return sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith('.report.json')), key=os.path.getmtime)


def _seen_recently(fp:str) -> bool:
    """True if a report with this fingerprint was queued within the hour; then only its count is increased."""
    with _lock:
        entry = _recent.get(fp)
        now = time.time()
        if entry is None or now - entry[0] >= SAME_FINGERPRINT_INTERVAL:
            return False
        entry[2] += 1
        if now - entry[3] >= 60:
            _flush_occurrences(fp, entry)
        return True


def _flush_occurrences(fp:str, entry:list[Any]) -> None:
    del fp
    if not entry[2]:
        return
    path = os.path.join(outbox_dir(), f'{entry[1]}.report.json')
    try:
        if os.path.exists(path): # else already sent; the extra count is dropped
            with open(path, encoding='utf-8') as f:
                q = json.load(f)
            q['occurrences'] = int(q.get('occurrences', 1)) + int(entry[2])
            _write_json(path, q)
    except Exception as e:  # pylint: disable=broad-except
        _log.debug(e)
    entry[2], entry[3] = 0, time.time()


def queue_report(report:dict[str, Any]) -> bool:
    """Puts the report into the local outbox unless the per-day cap is reached; an identical report (same
    fingerprint) within the hour only increments the occurrences of the queued one. Returns True if queued."""
    with _lock:
        d = outbox_dir()
        st = _load_state(d)
        now = time.time()
        day = time.strftime('%Y-%m-%d', time.gmtime(now))
        if st.get('day') != day:
            st['day'], st['count'] = day, 0
        fps:dict[str, Any] = {k: v for k, v in (st.get('fingerprints') or {}).items() if now - float(v.get('at', 0)) < SAME_FINGERPRINT_INTERVAL}
        fp = report['fingerprint']
        if fp in fps:
            queued = os.path.join(d, f"{fps[fp].get('id')}.report.json")
            if os.path.exists(queued):
                try:
                    with open(queued, encoding='utf-8') as f:
                        q = json.load(f)
                    q['occurrences'] = int(q.get('occurrences', 1)) + 1
                    _write_json(queued, q)
                except Exception as e:  # pylint: disable=broad-except
                    _log.debug(e)
            st['fingerprints'] = fps
            _write_json(os.path.join(d, STATE_FILE), st)
            return False
        if int(st.get('count', 0)) >= MAX_PER_DAY:
            return False
        _write_json(os.path.join(d, f"{report['client_report_id']}.report.json"), report)
        fps[fp] = {'at': now, 'id': report['client_report_id']}
        _recent[fp] = [now, report['client_report_id'], 0, now]
        st['fingerprints'] = fps
        st['count'] = int(st.get('count', 0)) + 1
        _write_json(os.path.join(d, STATE_FILE), st)
    _wakeup.set()
    return True


# --- entry points (never raise) ---

def report_exception(exc_type:type, exc_value:BaseException, tb:'TracebackType|None', kind:str = 'crash') -> bool:
    try:
        if not enabled():
            return False
        extracted = traceback.extract_tb(tb)
        frames = [(fs.filename, fs.name) for fs in extracted]
        if _seen_recently(fingerprint(exc_type.__name__, frames)):
            return False
        last = extracted[-1] if extracted else None
        line = f'{os.path.basename(last.filename)}:{last.lineno}' if last is not None else ''
        tb_text = ''.join(traceback.format_exception(exc_type, exc_value, tb))
        return queue_report(build_report(kind, exc_type.__name__, str(exc_value), tb_text, line, frames, _aw))
    except Exception as e:  # pylint: disable=broad-except
        _log.debug(e)
        return False


_RE_VOLATILE = re.compile(r'\d+(\.\d+)?')


def report_error(message:str, line:Any = None) -> bool:
    """An error recorded in the app's error log (adderror); grouped by its text without numbers."""
    try:
        if not enabled():
            return False
        text = str(message)
        first = text.splitlines()[0] if text else ''
        frames = [('adderror', _RE_VOLATILE.sub('#', first)[:200])]
        if _seen_recently(fingerprint('Error', frames)):
            return False
        stack = ''.join(traceback.format_stack(limit=12)[:-1])
        return queue_report(build_report('error', 'Error', text, stack, str(line or ''), frames, _aw))
    except Exception as e:  # pylint: disable=broad-except
        _log.debug(e)
        return False


# --- sender ---

def reports_url() -> str:
    from plus import config
    return f'{config.api_base_url}/client/reports'


def _post(report:dict[str, Any], authorized:bool) -> int|None:
    """Sends one report; returns the HTTP status or None if there was no response."""
    import gzip
    import requests
    from plus import connection, config
    headers = connection.getHeaders(authorized=authorized, decompress=False)
    if 'user-agent' not in headers: # the cloud module was never started (nobody logged in yet)
        p = report.get('platform') or {}
        headers['user-agent'] = f"Artisan/{(report.get('app') or {}).get('version', '')} ({p.get('os', '')}; {p.get('os_version', '')}; {p.get('arch', '')})"
    headers['Content-Type'] = 'application/json; charset=utf-8'
    headers['Content-Encoding'] = 'gzip'
    body = gzip.compress(json.dumps(report, ensure_ascii=False, default=str).encode('utf-8'))
    try:
        r = requests.post(reports_url(), data=body, headers=headers, verify=config.verify_ssl,
            timeout=(config.connect_timeout, config.read_timeout))
        return r.status_code
    except Exception as e:  # pylint: disable=broad-except
        _log.debug('error report not sent: %s', e)
        return None


def send_pending() -> bool:
    """Tries to send every queued report once. Returns False if the cloud was not reachable or asked to wait
    (no response, 404 before the endpoint is deployed, 408/429, 5xx) so the caller backs off."""
    d = outbox_dir()
    for path in pending_files(d):
        try:
            with open(path, encoding='utf-8') as f:
                report = json.load(f)
        except Exception:  # pylint: disable=broad-except
            os.remove(path) # unreadable: nothing to send
            continue
        logged_in = _logged_in()
        status = _post(report, authorized=logged_in)
        if status == 401 and logged_in:
            # expired session: send it anonymously with the last login instead
            last = _last_login()
            if last is not None:
                report['last_login'] = last
            status = _post(report, authorized=False)
        if status in {200, 201, 202, 413, 422}:
            # stored, or rejected for good (too large / invalid): never resend
            if status in {413, 422}:
                _log.warning('error report %s rejected by the cloud (%s)', report.get('client_report_id'), status)
            os.remove(path)
            continue
        return False
    return True


def _sender_loop() -> None:
    delay = SEND_INTERVAL
    while True:
        _wakeup.wait(delay)
        _wakeup.clear()
        try:
            if enabled() and send_pending():
                delay = SEND_INTERVAL
            else:
                delay = min(delay * 2, MAX_BACKOFF)
        except Exception as e:  # pylint: disable=broad-except
            _log.debug(e)
            delay = MAX_BACKOFF


def start(aw:'ApplicationWindow') -> None:
    """Starts the background sender (once); reports queued before (e.g. a crash at the last run) go out first."""
    global _aw, _sender # pylint: disable=global-statement
    _aw = aw
    if _sender is None:
        _sender = threading.Thread(target=_sender_loop, name='error-reports', daemon=True)
        _sender.start()
        _wakeup.set()
