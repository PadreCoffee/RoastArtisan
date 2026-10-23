"""Shows the cloud data that is not uploaded yet: items waiting in the outbox queue and items the server
rejected (kept in the outbox dead-letter file and re-sent automatically)."""
import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QCoreApplication, QDateTime
from PyQt6.QtWidgets import (QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, # pylint: disable=unused-import # QWidget is used in a string annotation
                             QHeaderView, QAbstractItemView, QWidget)

from plus import queue, config, controller, util
from artisanlib.dialogs import ArtisanDialog

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401

_log = logging.getLogger(__name__)
_tr = QCoreApplication.translate


def item_kind(item:dict[str, Any]) -> str:
    if queue.is_profile_upload_item(item):
        return _tr('Plus', 'Full profile')
    url = str(item.get('url', ''))
    if url.startswith(config.lock_schedule_url):
        return _tr('Plus', 'Schedule lock')
    if queue.is_full_roast_record(item.get('data') or {}):
        return _tr('Plus', 'Roast')
    return _tr('Plus', 'Roast change')


def item_label(item:dict[str, Any]) -> str:
    data = item.get('data') or {}
    batch = ''
    if data.get('batch_number'):
        batch = f"{data.get('batch_prefix', '')}{data['batch_number']} "
    label = str(data.get('label') or '')
    if batch or label:
        return f'{batch}{label}'.strip()
    roast_id = util.normalizeUUID(data.get('roast_id')) if data.get('roast_id') else None
    return roast_id[:8] if roast_id else '--'


def _when(iso:Any) -> str:
    try:
        epoch = util.ISO86012epoch(str(iso)) if iso else None
        if epoch:
            return QDateTime.fromSecsSinceEpoch(int(epoch)).toString('dd.MM.yyyy HH:mm')
    except Exception:  # pylint: disable=broad-except
        pass
    return ''


def rejected_state(entry:dict[str, Any]) -> str:
    reason = str(entry.get('reason') or '')
    if reason in queue.NOT_RETRIABLE_REASONS:
        return _tr('Plus', 'Not sent: the profile file is gone')
    status = entry.get('status')
    if status:
        return _tr('Plus', 'Rejected by the server ({0}), retried hourly').format(status)
    return _tr('Plus', 'Not accepted yet ({0}), retried hourly').format(reason)


# rows: (what, roast, since, state)
def unsent_rows() -> list[tuple[str, str, str, str]]:
    rows:list[tuple[str, str, str, str]] = []
    for item in queue.pending_items():
        rows.append((item_kind(item), item_label(item), _when((item.get('data') or {}).get('modified_at')), _tr('Plus', 'Waiting to be sent')))
    for entry in queue.dead_letter_entries():
        failed = entry.get('item')
        failed_item:dict[str, Any] = failed if isinstance(failed, dict) else {}
        rows.append((item_kind(failed_item), item_label(failed_item), _when(entry.get('failed_at')), rejected_state(entry)))
    return rows


class UnsentDialog(ArtisanDialog):
    def __init__(self, parent:'QWidget|None', aw:'ApplicationWindow') -> None:
        super().__init__(parent, aw)
        self.setWindowTitle(_tr('Form Caption', 'Unsent Cloud Data'))
        self.setModal(True)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([_tr('Table', 'What'), _tr('Table', 'Roast'), _tr('Table', 'Since'), _tr('Table', 'State')])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False) # type: ignore[union-attr]
        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setStretchLastSection(True)
        btnRetry = QPushButton(_tr('Button', 'Send now'))
        btnRetry.clicked.connect(self._send_now)
        btnRefresh = QPushButton(_tr('Button', 'Refresh'))
        btnRefresh.clicked.connect(self._reload)
        btnClose = QPushButton(_tr('Button', 'Close'))
        btnClose.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(btnRetry)
        row.addStretch()
        row.addWidget(btnRefresh)
        row.addWidget(btnClose)
        lay = QVBoxLayout()
        lay.addWidget(self.summary)
        lay.addWidget(self.table)
        lay.addLayout(row)
        self.setLayout(lay)
        self.resize(860, 360)
        self._reload()

    def _reload(self) -> None:
        rows = unsent_rows()
        self.table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
        if not rows:
            self.summary.setText(_tr('Plus', 'All data is uploaded to the cloud.'))
        elif controller.is_connected():
            self.summary.setText(_tr('Plus', 'Not uploaded yet: {0}. Sending is retried automatically.').format(len(rows)))
        else:
            self.summary.setText(_tr('Plus', 'Not uploaded yet: {0}. Sending resumes when the cloud connection is back.').format(len(rows)))

    def _send_now(self) -> None:
        try:
            queue.requeue_dead_letters()
            if controller.is_connected():
                queue.start()
        except Exception as e:  # pylint: disable=broad-except
            _log.exception(e)
        self._reload()
