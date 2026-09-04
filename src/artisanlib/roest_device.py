#
# ABOUT
# Roest USB device support for Artisan (native, Path B).
# Codec ported verbatim from RoestFirmwareUPD/roest-bridge (roest_record.py,
# roest_control.py, usb_bridge.py). Do not re-reverse-engineer — see that repo.

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
