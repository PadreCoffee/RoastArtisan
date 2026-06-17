"""Unit tests for the saved-operators store (multi-operator cloud login)."""
import sys
from PyQt6.QtCore import QSettings, QCoreApplication
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
QCoreApplication.setOrganizationName('roastartisan-test')
QCoreApplication.setApplicationName('operators-unittest')

import plus.operators as ops  # noqa: E402


def _clear():
    QSettings().remove(ops._SETTINGS_KEY)


def test_load_empty_returns_empty_list():
    _clear()
    assert ops.load_operators() == []


def test_save_then_load_roundtrip():
    _clear()
    entries = [ops.new_entry('a@x.io', 'Иван', 'https://artisan.plus', account_id='7')]
    ops.save_operators(entries)
    loaded = ops.load_operators()
    assert len(loaded) == 1
    assert loaded[0]['email'] == 'a@x.io'
    assert loaded[0]['nickname'] == 'Иван'
    assert loaded[0]['account_id'] == '7'
    assert loaded[0]['pin_hash'] is None


def test_upsert_adds_then_updates():
    entries: list = []
    entries = ops.upsert_operator(entries, 'a@x.io', 'Иван', 'https://artisan.plus', '7')
    assert len(entries) == 1
    # second upsert with same email updates nickname, does not duplicate
    entries = ops.upsert_operator(entries, 'a@x.io', 'Иван П.', 'https://artisan.plus', '7')
    assert len(entries) == 1
    assert entries[0]['nickname'] == 'Иван П.'


def test_find_and_remove():
    entries = ops.upsert_operator([], 'a@x.io', 'Иван', 'https://artisan.plus')
    entries = ops.upsert_operator(entries, 'b@x.io', 'Мария', 'https://artisan.plus')
    assert ops.find_operator(entries, 'b@x.io')['nickname'] == 'Мария'
    entries = ops.remove_operator(entries, 'a@x.io')
    assert ops.find_operator(entries, 'a@x.io') is None
    assert len(entries) == 1


def test_pin_set_verify_and_clear():
    entry = ops.new_entry('a@x.io', 'Иван', 'https://artisan.plus')
    assert ops.has_pin(entry) is False
    assert ops.verify_pin(entry, '9999') is True          # no PIN set -> always allowed
    ops.set_pin(entry, '1234')
    assert ops.has_pin(entry) is True
    assert entry['pin_hash'] != '1234'                    # never stored in plaintext
    assert ops.verify_pin(entry, '1234') is True
    assert ops.verify_pin(entry, '0000') is False
    ops.clear_pin(entry)
    assert ops.has_pin(entry) is False
