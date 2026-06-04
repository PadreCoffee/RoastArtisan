#
# queue.py
#
# Copyright (c) 2023, Paul Holleis, Marko Luther
# All rights reserved.
#
#
# ABOUT
# This module connects to the artisan.plus inventory management service

# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# version 3 of the License, or (at your option) any later versison. It is
# provided for educational purposes and is distributed in the hope that
# it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
# the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from PyQt6.QtCore import QCoreApplication, QObject, QThread, pyqtSlot, pyqtSignal, QSemaphore
from PyQt6.QtWidgets import QApplication

from artisanlib.util import getDirectory, serialize
from plus import config, util, roast, connection, sync, controller, register
import threading
import os
import tempfile
import time
import datetime
import requests.models
import json
import json.decoder
import logging
from typing import Final, Any, TYPE_CHECKING

if TYPE_CHECKING:
    import persistqueue # pylint: disable=unused-import


_log: Final[logging.Logger] = logging.getLogger(__name__)

queue_path = getDirectory(config.outbox_cache, share=False)

app = QCoreApplication.instance()

queue:'persistqueue.SQLiteQueue|None' = None # holdes the persistqueue.SQLiteQueue, initialized by start()

# queue entries are dictionaries with entries
#   url   : the URL to send the request to
#   data  : the data dictionary that will be send in the body as JSON
#   verb  : the HTTP verb to be used (POST or PUT)

PROFILE_UPLOAD_ITEM_TYPE: Final[str] = 'profile_upload'
PROFILE_UPLOAD_FIELD_NAME: Final[str] = 'file'


def is_profile_upload_item(item:dict[str, Any]) -> bool:
    return bool(item.get('type') == PROFILE_UPLOAD_ITEM_TYPE)


def get_response_json(r:requests.models.Response|None) -> dict[str, Any]|None:
    if r is None or r.status_code == 204:
        return None
    content_type = r.headers.get('content-type', '').strip()
    if not content_type.startswith('application/json'):
        return None
    try:
        res = r.json()
        return res if isinstance(res, dict) else None
    except json.decoder.JSONDecodeError as e:
        if not e.doc:
            _log.error('Empty response.')
        else:
            _log.error("Decoding error at char %s (line %s, col %s): '%s'", e.pos, e.lineno, e.colno, e.doc)
    except ValueError:
        _log.error('Response content is not valid JSON')
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
    return None


def extract_authoritative_roast_id(response:dict[str, Any]|None, fallback:str|None) -> str|None:
    fallback_normalized = util.normalizeUUID(fallback)
    if response is None:
        return fallback_normalized
    for key in ('roast_id', 'id'):
        value = response.get(key)
        if isinstance(value, str) and value != '':
            return util.normalizeUUID(value)
    result = response.get('result')
    if isinstance(result, dict):
        for key in ('roast_id', 'id'):
            value = result.get(key)
            if isinstance(value, str) and value != '':
                return util.normalizeUUID(value)
        roast_result = result.get('roast')
        if isinstance(roast_result, dict):
            for key in ('roast_id', 'id'):
                value = roast_result.get(key)
                if isinstance(value, str) and value != '':
                    return util.normalizeUUID(value)
    return fallback_normalized


def capture_profile_upload_source(roast_id:str) -> tuple[str|None, bool]:
    roast_id = util.normalizeUUID(roast_id) or roast_id
    aw = config.app_window
    if aw is None:
        return None, False

    if not aw.qmc.safesaveflag:
        try:
            if aw.curFile is not None and os.path.exists(aw.curFile):
                return aw.curFile, False
        except Exception as e:  # pylint: disable=broad-except
            _log.exception(e)
        try:
            profile_path = register.getPath(roast_id)
            if profile_path is not None and os.path.exists(profile_path):
                return profile_path, False
        except Exception as e:  # pylint: disable=broad-except
            _log.exception(e)

    try:
        profile = aw.getProfile()
        fd, tmp_path = tempfile.mkstemp(
            prefix=f'artisan-plus-{roast_id}-',
            suffix=f'.{config.profile_ext}',
        )
        os.close(fd)
        serialize(tmp_path, profile)
        return tmp_path, True
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
        return None, False


worker:'Worker|None' = None
worker_thread:QThread|None = None

queueWorkerSemaphore = QSemaphore(1) # ensure that only one worker thread is running


class Worker(QObject): # pyright: ignore [reportGeneralTypeIssues]
    startSignal = pyqtSignal()
    replySignal = pyqtSignal(float, float, str, int, list) # rlimit:float, rused:float, pu:str, notifications:int, machines:list[str]

    __slots__ = [ '_paused', '_state' ]

    def __init__(self) -> None:
        super().__init__()
        self._paused:bool = False  # start out non-paused
        self._state:threading.Condition = threading.Condition()

    @staticmethod
    def addSyncItem(item:dict[str, Any]) -> None:
        # successfully transmitted, we add/update the roasts UUID sync-cache
        if 'roast_id' in item['data'] and 'modified_at' in item['data']:
            roast_id = util.normalizeUUID(item['data']['roast_id'])
            if roast_id is None:
                return
            # we update the plus status icon
            sync.addSync(
                roast_id,
                util.ISO86012epoch(item['data']['modified_at']),
            )
            aw = config.app_window
            if aw is not None:
                aw.updatePlusStatusSignal.emit()  # @UndefinedVariable

    @pyqtSlot()
    def task(self) -> None:
        if queue is not None:
            from requests.exceptions import ConnectionError as RequestsConnectionError
            time.sleep(config.queue_start_delay)
            self.resume()  # unpause self
            item = None
            while True:
                time.sleep(config.queue_task_delay)
                with self._state:
                    if self._paused:
                        self._state.wait()  # block until notified
                _log.debug('-> qsize: %s', queue.qsize())
                _log.debug('looking for next item to be fetched')
                try:
                    if item is None:
                        item = queue.get()
                    _log.debug(
                        '-> worker processing item: %s', item
                    )
                    iters = 1 # by default, if no modified_at timestamp is given (no roast; maybe just a lock schedule message) thus we don't retry this
                    requeued = False
                    profile_item = is_profile_upload_item(item)
                    if 'url' not in item:
                        # items without an url are discarded
                        iters = 0
                    if 'data' in item and 'modified_at' in item['data']:
                        item_age = time.time()-util.ISO86012epoch(item['data']['modified_at'])
                        if (config.queue_discard_after > 0 and item_age > config.queue_discard_after):
                            # old item scheduled to be removed from the queue
                            iters = 0
                            _log.debug('-> expired item %s removed from queue (%s min)',item['data'].get('roast_id', '?'),int(round(item_age/60)))
                        else:
                            iters = config.queue_retries + 1
                    while iters > 0:
                        _log.debug(
                            '-> remaining iterations: %s', iters
                        )
                        r:requests.models.Response|None = None
                        try:
                            if profile_item:
                                roast_id = util.normalizeUUID(item['data'].get('roast_id')) if 'data' in item else None
                                if roast_id is None:
                                    iters = 0
                                elif sync.getSync(roast_id) is None:
                                    _log.warning('profile upload skipped for roast_id=%s: sync key missing', roast_id)
                                    if full_roast_in_queue(roast_id):
                                        _log.debug('requeue profile upload for roast_id=%s while full roast is still queued', roast_id)
                                        queue.put(item)
                                        requeued = True
                                    iters = 0
                                else:
                                    profile_path = item['data'].get('profile_path') if 'data' in item else None
                                    if not isinstance(profile_path, str) or not os.path.exists(profile_path):
                                        aw = config.app_window
                                        if aw is not None:
                                            aw.sendmessage(
                                                QApplication.translate(
                                                    'Plus',
                                                    'Roast summary uploaded, but full profile upload file is unavailable'
                                                )
                                            )  # @UndefinedVariable
                                        iters = 0
                                    else:
                                        controller.connect(
                                            clear_on_failure=False, interactive=False
                                        )
                                        r = connection.sendFile(
                                            item['url'], profile_path, field_name=PROFILE_UPLOAD_FIELD_NAME
                                        )
                                        r.raise_for_status()
                                        aw = config.app_window
                                        if aw is not None:
                                            aw.sendmessage(
                                                QApplication.translate(
                                                    'Plus',
                                                    'Full roast profile uploaded to {}'
                                                ).format(config.app_display_name)
                                            )  # @UndefinedVariable
                                        if item.get('cleanup_profile_path'):
                                            try:
                                                os.remove(profile_path)
                                            except OSError:
                                                pass
                                        iters = 0
                            elif is_full_roast_record(item['data']) or (
                                'roast_id' in item['data']
                                and sync.getSync(util.normalizeUUID(item['data']['roast_id']) or item['data']['roast_id'])
                            ):
                                controller.connect(
                                    clear_on_failure=False, interactive=False
                                )
                                r = connection.sendData(
                                    item['url'], item['data'], item['verb']
                                )
                                r.raise_for_status()
                                aw = config.app_window
                                if aw is not None:
                                    aw.sendmessage(
                                        QApplication.translate(
                                            'Plus',
                                            'Roast successfully uploaded to {}'
                                        ).format(config.app_display_name)
                                    )  # @UndefinedVariable
                                self.addSyncItem(item)
                                sr, h = roast.getSyncRecord()
                                if util.normalizeUUID(item['data']['roast_id']) == util.normalizeUUID(sr['roast_id']):
                                    sync.setSyncRecordHash(sync_record=sr, h=h)

                                response = get_response_json(r)
                                if response:
                                    rlimit,rused,pu,notifications, machines = util.extractAccountState(response)
                                    self.replySignal.emit(rlimit,rused,pu,notifications,machines)

                                if is_full_roast_record(item['data']) and config.profile_upload_enabled():
                                    profile_path = item.get('profile_path')
                                    authoritative_roast_id = extract_authoritative_roast_id(
                                        response,
                                        item['data'].get('roast_id'),
                                    )
                                    if (
                                        isinstance(profile_path, str)
                                        and os.path.exists(profile_path)
                                        and authoritative_roast_id is not None
                                    ):
                                        addProfileUpload(
                                            authoritative_roast_id,
                                            profile_path,
                                            bool(item.get('cleanup_profile_path', False)),
                                        )
                            elif 'url' in item and item['url'].startswith(config.lock_schedule_url):
                                controller.connect(
                                    clear_on_failure=False, interactive=False
                                )
                                r = connection.sendData(
                                    item['url'], item['data'], item['verb']
                                )
                                r.raise_for_status()

                            iters = 0
                        except RequestsConnectionError as e:
                            try:
                                if controller.is_connected():
                                    _log.debug(
                                        ('-> connection error,'
                                         ' disconnecting: %s'),
                                        e,
                                    )
                                    controller.disconnect(
                                        remove_credentials=False, stop_queue=True
                                    )
                            except Exception as ex:  # pylint: disable=broad-except
                                _log.exception(ex)
                            time.sleep(config.queue_retry_delay)
                        except Exception as e:  # pylint: disable=broad-except
                            _log.debug('-> task failed: %s', e)
                            if r is not None:
                                _log.debug(
                                    '-> status code %s', r.status_code
                                )
                            else:
                                _log.debug('-> no status code')
                            if (
                                r is not None and r.status_code == 401
                            ):
                                try:
                                    if controller.is_connected():
                                        _log.debug(
                                            ('-> connection error,'
                                             ' disconnecting: %s'),
                                            e,
                                        )
                                        controller.disconnect(
                                            remove_credentials=False,
                                            stop_queue=False,
                                        )
                                except Exception as ex:  # pylint: disable=broad-except
                                    _log.exception(ex)
                                iters = iters - 1
                                time.sleep(config.queue_retry_delay)
                            elif (
                                r is not None and r.status_code == 409
                            ):
                                iters = 0
                            else:
                                iters = iters - 1
                                time.sleep(2*config.queue_retry_delay)

                            if profile_item and not requeued and iters == 0:
                                aw = config.app_window
                                if aw is not None:
                                    aw.sendmessage(
                                        QApplication.translate(
                                            'Plus',
                                            'Roast summary uploaded, but full profile upload failed'
                                        )
                                    )  # @UndefinedVariable
                    queue.task_done()
                    item = None
                    _log.debug(
                        'end of run:while paused=%s', self._paused
                    )
                except Exception as e:  # pylint: disable=broad-except
                    _log.exception(e)

    def resume(self) -> None:
        _log.debug('resume()')
        with self._state:
            self._paused = False
            self._state.notify()  # unblock self if waiting

    def pause(self) -> None:
        _log.debug('pause()')
        with self._state:
            self._paused = True  # make self block and wait

# will be evaluated in GUI thread
def processReply(rlimit:float, rused:float, pu:str, notifications:int, machines:list[str]) -> None:
    try:
#        _log.debug('thread id', threading.get_ident())
        _log.debug('processReply(%s,%s,%s,%s,%s', rlimit, rused, pu, notifications, machines)
    except Exception:  # pylint: disable=broad-except
        pass

def start() -> None:
#    if app.artisanviewerMode:
#        _log.info(
#            "start(): queue not started in ArtisanViewer mode"
#        )
#        return
    global queue  # pylint: disable=global-statement
    global worker, worker_thread  # pylint: disable=global-statement

    try:
        queueWorkerSemaphore.acquire(1)
        if queue is None:
            # we initialize the queue
            import persistqueue
            if hasattr(persistqueue, 'SQLiteQueue'):
                try:
                    queue = persistqueue.SQLiteQueue(
                        queue_path, multithreading=True, auto_commit=False
                    )
                    # we keep items in the queue if not explicit marked as task_done:
                    # auto_commit=False
                except Exception:  # pylint: disable=broad-except
                    pass
        _log.debug('start()')
        if queue is not None:
            _log.debug('-> qsize: %s', queue.qsize())
        if worker_thread is None:
            worker = Worker()
            worker_thread = QThread()
            worker_thread.start()
            worker.moveToThread(worker_thread)
            worker.startSignal.connect(worker.task)
            worker.replySignal.connect(util.updateLimits)
            #app.aboutToQuit.connect(end)
            worker.startSignal.emit()
            _log.debug('queue started')
        elif worker is not None:
            worker.resume()
            _log.debug('queue resumed')
    finally:
        if queueWorkerSemaphore.available() < 1:
            queueWorkerSemaphore.release(1)


# the queue worker thread cannot really be stopped, but we can pause it
def stop() -> None:  # pylint: disable=global-statement
    if worker is not None:
        try:
            queueWorkerSemaphore.acquire(1)
            worker.pause()
            _log.debug('queue stopped')
        finally:
            if queueWorkerSemaphore.available() < 1:
                queueWorkerSemaphore.release(1)


# check if a full roast record (one with date) with roast_id is in the queue
# this is used to add also items to the queue that are not yet registered in
# the sync cache as they are not yet uploaded successfully to the server as their initial item
# is still stuck in the outgoing queue
def full_roast_in_queue(roast_id: str) -> bool:
    roast_id = util.normalizeUUID(roast_id) or roast_id
    import persistqueue
    if hasattr(persistqueue, 'SQLiteQueue'):
        q = None
        try:
            q = persistqueue.SQLiteQueue(
                queue_path, multithreading=True, auto_commit=False
            )
            while True:
                item = q.get(block=False)
                if 'data' in item:
                    r = item['data']
                    if is_full_roast_record(r) and roast_id == (util.normalizeUUID(r['roast_id']) or r['roast_id']):
                        # there is a full roast record already in queue
                        break
            del q
            return True
        except Exception:  # pylint: disable=broad-except
            # we reached the end of the queue
            pass
        del q # noqa: F821
    return False


################

# returns true if the given roast_record r is a full record containing all
# information (incl. the roast date) and not only an update
def is_full_roast_record(r:dict[str, Any]) -> bool:
    return bool('date' in r and r['date'] and 'amount' in r and 'roast_id' in r)

# holds the last queued roast item
last_queued_roast_item:dict[str, Any]|None = None
last_queued_profile_item:tuple[str, str, int, int]|None = None


# adds given item to the outgoing queue to be send to the server, but ignores items that contain no additional information over the item just queued before (last_queued_roast).
# NOTE: it can happen that the new item to be queued (queued on SAVE/AUTOSAVE) is just an update of a previous queued roast but not yet send roast (queued on DROP) and thus the
#   mechanism (via sync.py cached_sync_record_hash/cached_sync_record) to just send updates does not yet applies.
def queue_roast_item(
    roast_item:dict[str, Any],
    profile_path:str|None = None,
    cleanup_profile_path:bool = False,
) -> bool:
    global last_queued_roast_item  # pylint: disable=global-statement

    def roast_subset_of(roast1:dict[str, Any], roast2:dict[str, Any]) -> bool:
        return all(item in roast2.items() for item in roast1.items() if item[0] != 'modified_at')

    queued:bool = False
    if queue is None:
        _log.info(
            '-> roast not queued as queue'
                ' is not running')
    elif last_queued_roast_item is None or not roast_subset_of(roast_item, last_queued_roast_item):
        queue_item:dict[str, Any] = {'url': config.roast_url, 'data': roast_item, 'verb': 'POST'}
        if profile_path is not None:
            queue_item['profile_path'] = profile_path
            queue_item['cleanup_profile_path'] = cleanup_profile_path
        queue.put(
            queue_item,
            # timeout=config.queue_put_timeout
            # sql queue does not feature a timeout
        )
        queued = True
        last_queued_roast_item = roast_item

    return queued


def addProfileUpload(
    roast_id:str|None,
    profile_path:str|None,
    cleanup_profile_path:bool = False,
) -> bool:
    roast_id = util.normalizeUUID(roast_id)
    global last_queued_profile_item  # pylint: disable=global-statement

    if (
        not config.profile_upload_enabled()
        or queue is None
        or roast_id is None
        or roast_id == ''
        or profile_path is None
    ):
        return False

    profile_path = os.path.abspath(profile_path)
    if not os.path.exists(profile_path):
        return False

    stat = os.stat(profile_path)
    signature = (roast_id, profile_path, int(stat.st_mtime_ns), int(stat.st_size))
    if last_queued_profile_item == signature:
        return False

    queue.put(
        {
            'type': PROFILE_UPLOAD_ITEM_TYPE,
            'url': config.get_profile_upload_url(roast_id),
            'data': {
                'roast_id': roast_id,
                'profile_path': profile_path,
                'modified_at': util.epoch2ISO8601(time.time()),
            },
            'verb': 'POST',
            'cleanup_profile_path': cleanup_profile_path,
        },
    )
    last_queued_profile_item = signature
    return True

# called on completed roasts with roast data
# if roast_record is given, we assume an update is queued, otherwise a new
# roast is queued
#   a full roast_record requires at least
#      - roast_id
#      - date
#      - amount
#   an update only the roast_id
# if unsynced is set (roast was not yet in sync DB) we always set current time as modified_at, overwriting the last saved dated
# that might have been set by roast.getRoast()
def addRoast(roast_record:dict[str, Any]|None = None, unsynced:bool=False) -> None:
    try:
        _log.debug('addRoast(%s, %s)', roast_record, unsynced)
        aw = config.app_window
        if aw is None:
            _log.info('config.app_window is None')
        elif aw.plus_readonly:
            _log.info(
                '-> roast not queued as users'
                 ' account access is readonly'
            )
        elif queue is None:
            _log.info(
                '-> roast not queued as queue'
                 ' is not running'
            )
        else:
            r: dict[str, Any]
            r = roast.getRoast() if roast_record is None else roast_record
            # if modification date is not set yet, we add the current time as
            # modified_at timestamp as float EPOCH with millisecond
            if unsynced or 'modified_at' not in r:
                r['modified_at'] = util.epoch2ISO8601(time.time())
            _log.debug('-> roast: %s', r)
            # check if all required data is available before queueing this up
            if (
                'roast_id' in r
                and r['roast_id']
                and (
                    roast_record is not None
                    or ('date' in r and r['date'] and 'amount' in r)
                )
            ):  # amount can be 0 but has to be present
                # put in upload queue
                _log.debug('-> put in queue')
                aw.sendmessage(
                    QApplication.translate(
                        'Plus',
                        'Queuing roast for upload to {}'
                    ).format(config.app_display_name)
                )  # @UndefinedVariable
                rr: dict[str, Any]
                if roast_record is not None:
                    # on updates only changed attributes w.r.t. the current
                    # cached sync record are uploaded
                    rr = sync.diffCachedSyncRecord(r)
                else:
                    rr = r
                # send zero values like 0 and '' for corresponding attributes as None to allow the server to clean those up
                rr = sync.suppress_zero_values(rr)
                profile_path:str|None = None
                cleanup_profile_path:bool = False
                if is_full_roast_record(rr) and config.profile_upload_enabled():
                    profile_path, cleanup_profile_path = capture_profile_upload_source(rr['roast_id'])
                queued:bool = queue_roast_item(
                    rr,
                    profile_path=profile_path,
                    cleanup_profile_path=cleanup_profile_path,
                )
                if queued:
                    _log.debug('-> roast queued up')
                    if 'roast_id' in rr:
                        _log.info('roast queued: %s', rr['roast_id'])
                    _log.debug('-> qsize: %s', queue.qsize())
            else:
                _log.debug(
                    '-> roast not queued as mandatory info missing'
                )
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)

def sendLockSchedule() -> None:
    try:
        _log.debug('sendLockSchedule()')
        aw = config.app_window
        if aw is None:
            _log.info('config.app_window is None')
        elif aw.plus_readonly:
            _log.info(
                '-> lockSchedule not queued as users'
                 ' account access is readonly'
            )
        elif queue is None:
            _log.info(
                '-> lockSchedule not queued as queue'
                 ' is not running'
            )
        else:
            queue.put(
                {'url': f'{config.lock_schedule_url}?today={datetime.datetime.now().astimezone().date()}', 'data': {}, 'verb': 'POST'},
                # timeout=config.queue_put_timeout
                # sql queue does not feature a timeout
            )
            _log.debug('-> lockSchedule queued up')
            aw.qmc.registerLockScheduleSent()
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
