"""Unit tests for the roest(<chan>,<value>) eventaction IO-command parser.

`roest(<chan>,<value>)` is an eventaction/IO-command that drives
`aw.roest.send_msg(chan, value)` (Task 2) via the `roestSendMessageSignal` Qt
signal (Task 7), mirroring the existing `santoker(...)` control-out command.

Only `chan` in {'drum','fan','power'} are wired; `drop` (P4) is intentionally
left unwired (unsafe) since it is normally driven by the roaster itself, not
by the operator. The command parsing is extracted into the pure helper
`artisanlib.main._parse_roest_command()` so it can be unit-tested without
touching Qt signals, `aw.roest`, or the full `ApplicationWindow`.
"""

import sys

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main  # noqa: E402,F401  (upgrades the QApplication instance)
from artisanlib.main import _parse_roest_command  # noqa: E402


class TestParseRoestCommandWiredChannels:
    """chan in {'drum','fan','power'} should parse to (chan, value)."""

    @pytest.mark.parametrize(
        ('cmd', 'expected_chan', 'expected_value'),
        [
            ('roest(drum,40)', 'drum', 40.0),
            ('roest(fan,60)', 'fan', 60.0),
            ('roest(power,50)', 'power', 50.0),
            ('roest(DRUM,40)', 'drum', 40.0),  # chan is matched case-insensitively
            ('roest( fan , 60.5 )', 'fan', 60.5),  # surrounding whitespace is tolerated
            ('roest(power,0)', 'power', 0.0),
            ('roest(drum,-1)', 'drum', -1.0),
        ],
    )
    def test_wired_channels_parse(self, cmd: str, expected_chan: str, expected_value: float) -> None:
        result = _parse_roest_command(cmd)
        assert result == (expected_chan, expected_value)


class TestParseRoestCommandUnwiredOrInvalid:
    """The drop/P4 channel and any malformed input must yield None (logged and ignored)."""

    def test_drop_channel_returns_none(self) -> None:
        # P4/DROP is intentionally not wired (unsafe): it must be parsed but ignored.
        assert _parse_roest_command('roest(drop,1)') is None

    @pytest.mark.parametrize(
        'cmd',
        [
            'roest(bogus,1)',      # unknown channel
            'roest()',             # empty args
            'roest(drum)',         # missing value
            'roest(drum,notafloat)',  # unparsable value
            'roest',               # no parens at all
            'roest(drum,40',       # missing closing paren
            'roest(,40)',          # missing channel
        ],
    )
    def test_malformed_or_unknown_returns_none(self, cmd: str) -> None:
        assert _parse_roest_command(cmd) is None
