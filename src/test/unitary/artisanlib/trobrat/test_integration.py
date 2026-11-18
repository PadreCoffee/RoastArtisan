"""The bundled machine preset and gateway lifecycle never contact a real PLC."""

from pathlib import Path
import threading
from unittest import mock

from PyQt6.QtCore import QSettings  # type: ignore[import-not-found]

from artisanlib.trobrat import bernin_control, service


def test_machine_preset_maps_only_this_roaster() -> None:
    path = Path(__file__).resolve().parents[4] / 'includes/Machines/Trobrat/Bernin-Control.aset'
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    assert settings.value('Trobrat/enabled') == 'true'
    assert settings.value('Trobrat/host') == settings.value('S7/host')
    assert settings.value('Modbus/host') == '127.0.0.1'
    assert settings.value('Modbus/port') == '15020'
    assert settings.value('S7/area') == ['6', '6', '6', '0', '0', '0', '0', '0', '0', '0', '0', '0']
    assert settings.value('ExtraEventButtons/buttonlistmaxlen') == '13'
    actions = settings.value('ExtraEventButtons/extraeventsactions')
    commands = settings.value('ExtraEventButtons/extraeventsactionstrings')
    labels = settings.value('ExtraEventButtons/extraeventslabels')
    assert len(actions) == len(commands) == len(labels) == 13
    assert set(actions) == {'4'}
    assert commands[-6:] == [
        'writeWord(1,106,1)', 'writeWord(1,106,0)',
        'writeWord(1,108,1)', 'writeWord(1,108,0)',
        'writeWord(1,110,1)', 'writeWord(1,110,0)',
    ]


def test_gateway_lifecycle_does_not_write_on_start() -> None:
    stopped = threading.Event()
    calls: list[str] = []

    class FakeServer:
        def __init__(self, gateway) -> None:
            assert gateway is not None

        def serve_forever(self) -> None:
            stopped.wait()

        def shutdown(self) -> None:
            stopped.set()

        def server_close(self) -> None:
            calls.append('server_closed')

    def fake_poll(_gateway, stop_event: threading.Event) -> None:
        stop_event.wait()

    with mock.patch.object(bernin_control, 'Server', FakeServer), mock.patch.object(bernin_control, 'poll', fake_poll), \
            mock.patch.object(bernin_control.ControlReader, 'close', autospec=True) as close:
        gateway = service.TrobratService('127.0.0.1')
        gateway.start()
        assert not gateway.stop_event.is_set()
        assert calls == []
        gateway.stop()
        assert gateway.stop_event.is_set()
        assert calls == ['server_closed']
        close.assert_called_once()
