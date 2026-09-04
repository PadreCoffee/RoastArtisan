#
# ABOUT
# Roest USB device support for Artisan (native, Path B).
# Codec ported verbatim from RoestFirmwareUPD/roest-bridge (roest_record.py,
# roest_control.py, usb_bridge.py). Do not re-reverse-engineer — see that repo.

# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# version 3 of the License, or (at your option) any later version. It is
# provided for educational purposes and is distributed in the hope that
# it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
# the GNU General Public License for more details.

import asyncio
import logging
import struct
from collections.abc import Iterator
from typing import Any, Final, override, TYPE_CHECKING

if TYPE_CHECKING:
    from artisanlib.atypes import SerialSettings  # pylint: disable=unused-import

from artisanlib.async_comm import AsyncComm, IteratorReader

_log: Final[logging.Logger] = logging.getLogger(__name__)

# --- telemetry framing/decoding (ported: usb_bridge.deframe + roest_record.decode_record) ---
MAGIC: Final[bytes] = b'\xA5\x5A'
RECORD_LEN: Final[int] = 22
FRAME_LEN: Final[int] = 2 + RECORD_LEN + 1   # magic + record + xor = 25


def _cC(v: int) -> float | None:
    return None if v == 0xFFFF else v / 100.0


def decode_record(b: bytes) -> dict[str, Any]:
    if len(b) != RECORD_LEN:
        raise ValueError(f'record must be {RECORD_LEN} bytes, got {len(b)}')
    bt, et, rtd2, rtd3, drum, inlet, target = struct.unpack_from('<7H', b, 0)
    pcb = b[0x0E]
    t_state = struct.unpack_from('<H', b, 0x10)[0]
    packed = struct.unpack_from('<I', b, 0x12)[0]
    return {
        'bt': _cC(bt), 'et': _cC(et), 'rtd2': _cC(rtd2), 'rtd3': _cC(rtd3),
        'drum_temp': _cC(drum), 'inlet_temp': _cC(inlet), 'target': _cC(target),
        'pcb_temperature': pcb,
        'msec': (t_state & 0x1FFF) * 1000,
        'phase': (t_state >> 14) & 0x3,
        'crack': packed & 0xFF,
        'heat': ((packed >> 8) & 0x3FF) / 10.0,
        'rpm': (packed >> 18) & 0x7F,
        'fan': (packed >> 25) & 0x7F,
    }


def deframe(buf: bytearray) -> Iterator[bytes]:
    """Yield validated 22-byte records from a rolling byte buffer; resync on error."""
    while True:
        i = buf.find(MAGIC)
        if i < 0:
            if buf and buf[-1] == MAGIC[0]:
                del buf[:-1]
            else:
                buf.clear()
            return
        if len(buf) - i < FRAME_LEN:
            del buf[:i]
            return
        rec = bytes(buf[i + 2:i + 2 + RECORD_LEN])
        xor = buf[i + 2 + RECORD_LEN]
        chk = 0
        for x in rec:
            chk ^= x
        if chk == xor:
            del buf[:i + FRAME_LEN]
            yield rec
        else:
            del buf[:i + 1]

# --- control encoding (ported: roest_control) ---
CTRL_MAGIC: Final[bytes] = b'\x5A\xA5'
CTRL_REPEAT: Final[int] = 8
CHAN: Final[dict[str, int]] = {'drum': 0x44, 'fan': 0x46, 'power': 0x50}
RANGES: Final[dict[str, tuple[int, int]]] = {'drum': (20, 65), 'fan': (30, 100), 'power': (0, 100)}


def clamp(chan: str, value: float) -> float:
    lo, hi = RANGES[chan]
    v = max(lo, min(hi, value))
    return v if chan == 'power' else int(v)


def encode(chan: str, value: int) -> bytes:
    """5-byte drum/fan command (value pre-clamped)."""
    c = CHAN[chan]
    v = int(value) & 0xFF
    return CTRL_MAGIC + bytes([c, v, c ^ v])


def encode_power(pct: float) -> bytes:
    """8-byte power command: fraction (clamped pct/100) as f32 LE + xor."""
    frac = max(0.0, min(1.0, clamp('power', pct) / 100.0))
    fb = struct.pack('<f', frac)
    x = 0x50
    for b in fb:
        x ^= b
    return CTRL_MAGIC + bytes([0x50]) + fb + bytes([x])


class Roest(AsyncComm):

    __slots__ = ['_charge_handler', '_dry_handler', '_fcs_handler', '_drop_handler',
                 '_bt', '_et', '_heat', '_fan', '_rpm', '_drum_temp', '_inlet_temp', '_target',
                 '_phase', '_crack']

    def __init__(self, host: str = '127.0.0.1', port: int = 8080, serial: 'SerialSettings|None' = None,
                 connected_handler=None, disconnected_handler=None,
                 charge_handler=None, dry_handler=None, fcs_handler=None, drop_handler=None) -> None:
        super().__init__(host, port, serial, connected_handler, disconnected_handler)
        self._charge_handler = charge_handler
        self._dry_handler = dry_handler
        self._fcs_handler = fcs_handler
        self._drop_handler = drop_handler
        self._bt: float = -1
        self._et: float = -1
        self._heat: float = -1
        self._fan: float = -1
        self._rpm: float = -1
        self._drum_temp: float = -1
        self._inlet_temp: float = -1
        self._target: float = -1
        self._phase: int = -1
        self._crack: int = -1

    # getters (Artisan reads these each tick; -1 == no value)
    def getBT(self) -> float: return self._bt
    def getET(self) -> float: return self._et
    def getHeat(self) -> float: return self._heat
    def getFan(self) -> float: return self._fan
    def getRPM(self) -> float: return self._rpm
    def getDrumTemp(self) -> float: return self._drum_temp
    def getInletTemp(self) -> float: return self._inlet_temp
    def getTarget(self) -> float: return self._target

    @override
    def reset_readings(self) -> None:
        self._bt = self._et = self._heat = self._fan = self._rpm = -1
        self._drum_temp = self._inlet_temp = self._target = -1
        self._phase = self._crack = -1

    @staticmethod
    def _num(v: float | None) -> float:
        return -1 if v is None else v

    def register_reading(self, rec: dict[str, Any]) -> None:
        self._bt = self._num(rec['bt'])
        self._et = self._num(rec['et'])
        self._heat = rec['heat']
        self._fan = rec['fan']
        self._rpm = rec['rpm']
        self._drum_temp = self._num(rec['drum_temp'])
        self._inlet_temp = self._num(rec['inlet_temp'])
        self._target = self._num(rec['target'])
        # NOTE: event emission from rec['phase']/rec['crack'] is added in Task 8
        # (mapping confirmed on the bench). Keep the fields for that task:
        self._phase = rec['phase']
        self._crack = rec['crack']

    @override
    async def read_msg(self, stream: 'asyncio.StreamReader|IteratorReader') -> None:
        await stream.readuntil(MAGIC)              # consume through the 2-byte magic
        rec = await stream.readexactly(RECORD_LEN)
        xor = await stream.readexactly(1)
        chk = 0
        for x in rec:
            chk ^= x
        if xor[0] != chk:
            if self._logging:
                _log.debug('XOR mismatch, resync')
            return
        try:
            self.register_reading(decode_record(rec))
        except Exception as e:  # pylint: disable=broad-except
            if self._logging:
                _log.debug('decode error: %s', e)

    def send_msg(self, chan: str, value: float) -> None:
        if chan == 'power':
            frame = encode_power(value)
        else:
            frame = encode(chan, int(clamp(chan, value)))
        self.send(frame * CTRL_REPEAT)             # 8x burst
