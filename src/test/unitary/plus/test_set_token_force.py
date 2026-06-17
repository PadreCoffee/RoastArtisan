"""setToken must overwrite a non-empty operator only when force_operator=True."""
import sys
from unittest.mock import Mock
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
import plus.config as config        # noqa: E402
import plus.connection as connection  # noqa: E402


def _aw_with_operator(value):
    aw = Mock()
    aw.qmc = Mock()
    aw.qmc.operator = value
    aw.qmc.operator_setup = ''
    return aw


def test_set_token_does_not_clobber_when_not_forced():
    config.app_window = _aw_with_operator('Existing')
    connection.setToken('tok', nickname='Иван')
    assert config.app_window.qmc.operator == 'Existing'   # unchanged on normal login


def test_set_token_fills_empty_operator():
    config.app_window = _aw_with_operator('')
    connection.setToken('tok', nickname='Иван')
    assert config.app_window.qmc.operator == 'Иван'


def test_set_token_force_overwrites_and_sets_default():
    config.app_window = _aw_with_operator('Existing')
    connection.setToken('tok', nickname='Мария', force_operator=True)
    assert config.app_window.qmc.operator == 'Мария'
    assert config.app_window.qmc.operator_setup == 'Мария'
