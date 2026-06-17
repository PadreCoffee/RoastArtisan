"""Manage saved cloud operators: remove, set/clear PIN, add."""
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout,
                             QPushButton, QInputDialog, QLineEdit, QMessageBox, QWidget)

import plus.operators as operators
from artisanlib.dialogs import ArtisanDialog

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401

_log = logging.getLogger(__name__)
_tr = QCoreApplication.translate


class OperatorsDialog(ArtisanDialog):
    def __init__(self, parent:'QWidget|None', aw:'ApplicationWindow') -> None:
        super().__init__(parent, aw)
        self.setWindowTitle(_tr('Form Caption', 'Manage Operators'))
        self.listw = QListWidget()
        self._reload()
        btnPin = QPushButton(_tr('Button', 'Set/Clear PIN'))
        btnPin.clicked.connect(self._toggle_pin)
        btnRemove = QPushButton(_tr('Button', 'Remove'))
        btnRemove.clicked.connect(self._remove)
        btnAdd = QPushButton(_tr('Button', 'Add'))
        btnAdd.clicked.connect(self._add)
        btnClose = QPushButton(_tr('Button', 'Close'))
        btnClose.clicked.connect(self.accept)
        row = QHBoxLayout()
        for b in (btnAdd, btnPin, btnRemove, btnClose):
            row.addWidget(b)
        lay = QVBoxLayout()
        lay.addWidget(self.listw)
        lay.addLayout(row)
        self.setLayout(lay)

    def _reload(self) -> None:
        self.listw.clear()
        for e in operators.load_operators():
            label = (e.get('nickname') or e['email'])
            if operators.has_pin(e):
                label += '  🔒'
            item = QListWidgetItem(label)
            item.setData(256, e['email'])   # Qt.ItemDataRole.UserRole == 256
            self.listw.addItem(item)

    def _selected_email(self):
        it = self.listw.currentItem()
        return None if it is None else it.data(256)

    def _toggle_pin(self) -> None:
        email = self._selected_email()
        if not email:
            return
        ops_list = operators.load_operators()
        entry = operators.find_operator(ops_list, email)
        if entry is None:
            return
        if operators.has_pin(entry):
            operators.clear_pin(entry)
        else:
            pin, ok = QInputDialog.getText(self, _tr('Message', 'Set PIN'),
                                           _tr('Message', 'New PIN (digits):'),
                                           QLineEdit.EchoMode.Password)
            if not ok or not pin:
                return
            operators.set_pin(entry, pin)
        operators.save_operators(ops_list)
        self._reload()

    def _remove(self) -> None:
        email = self._selected_email()
        if not email:
            return
        operators.save_operators(operators.remove_operator(operators.load_operators(), email))
        # offer to also delete the saved password from the keyring
        if QMessageBox.question(self, _tr('Message', 'Remove password'),
                                _tr('Message', 'Also delete the saved password for {0}?').format(email)
                                ) == QMessageBox.StandardButton.Yes:
            try:
                import keyring
                import plus.config as config
                keyring.delete_password(config.get_keyring_service_name(), email)
            except Exception as e:  # pylint: disable=broad-except
                _log.exception(e)
        self._reload()

    def _add(self) -> None:
        import plus.controller as plus_controller
        plus_controller.connect(self.aw)
        self._reload()
