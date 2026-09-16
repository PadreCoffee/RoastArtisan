# Roest native device (Option A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native `Roest(AsyncComm)` USB-serial device to RoastArtisan so the roaster picks "Roest BT/ET" in device settings and streams temps + drives roast marks + sends drum/fan/power control — no external bridge, no WebSocket, no subprocess.

**Architecture:** One new module `artisanlib/roest_device.py` (`class Roest(AsyncComm)`, modeled line-for-line on `Santoker` in `artisanlib/santoker.py:94`), plus the fixed `ADD DEVICE:` seam entries. The Roest USB wire codec (frame `A5 5A`+22+XOR telemetry; `5A A5` control) is **ported verbatim** from the already-reversed `roest-bridge/` (`roest_record.py`, `roest_control.py`, `usb_bridge.py`) into the module — no re-reverse-engineering. Temps/extras are pulled by a `comm.py` reader; roast events are emitted as Qt signals from the reader (as Kaleido/Santoker do).

**Tech Stack:** Python 3, PyQt6, asyncio (`AsyncComm` base `artisanlib/async_comm.py:252`), pyserial-asyncio (already used by AsyncComm serial path), `struct`.

**Spec:** `/Users/lectrisheep/Desktop/RoestFirmwareUPD/roest-bridge/docs/2026-09-04-artisan-native-roest-integration-audit.md` (audit). Wire facts: `/Users/lectrisheep/Desktop/RoestFirmwareUPD/HANDOFF.md`. Reference codec: `roest-bridge/{roest_record,roest_control,usb_bridge}.py`.

## Global Constraints

- **Port the codec, do not re-derive it.** `decode_record` (roest_record.py:25), `deframe` framing (usb_bridge.py:100), `encode`/`encode_power`/`clamp`/`CHAN`/`RANGES` (roest_control.py) are copied into `roest_device.py`. Drop the `roest_decoder.RoastSample` import and `record_to_sample`, and drop the WS/serial-loop glue — keep only the pure functions.
- **Model on Santoker 1:1.** `santoker.py:94-399` is the template (framed byte stream over serial + control back + event signals). Base class API: `artisanlib/async_comm.py:252` (`__init__(host,port,serial,connected_handler,disconnected_handler)`, `send(bytes)`, `start()`, `stop()`, override `read_msg(stream)` and `reset_readings()`).
- **Follow `ADD DEVICE:`** — `grep -rn "ADD DEVICE:" src/artisanlib` is the canonical seam checklist (canvas.py, comm.py, devices.py).
- **Transport:** USB CDC serial, `/dev/tty.usbmodem*` (macOS name drifts `1101`↔`11101` — auto-pick the first match), **115200** 8N1.
- **Telemetry frame:** `A5 5A | 22 record bytes | XOR-of-22`. `0xFFFF` in a °C×100 field ⇒ sensor absent ⇒ Artisan `-1`.
- **Control frames:** `5A A5 <chan> …`; send each as an **8× burst** (`CONTROL_REPEAT=8`). Drum 20–65 (`'D'` u8), fan 30–100 step5 (`'F'` u8), power 0.0–1.0 (`'P'` f32 LE).
- **P4 — Artisan→roaster DROP is NOT safe yet** (the event-record route caused a motor-stuck fault). Leave a `roest("drop", …)` command slot but **DO NOT wire it**. dev-time% is deferred too.
- **Events:** the roaster auto-detects CHARGE/TP/DRY/FC/DROP and reports `phase`+`crack` in telemetry. Drive Artisan marks from the reader (no roaster command). **The exact `phase`/`crack` → event mapping is NOT in the ported codec and MUST be confirmed on the bench (Task 8).**
- **Channel mapping (confirm on the bench, Task 9):** temp1=ET, temp2=BT (Santoker convention). Extras: heat% / fan% / rpm / drum_temp / inlet_temp / target.
- **No Roest hardware in the build environment.** Everything hardware-independent (the codec) is unit-tested here; the device registration, live streaming, event marks and control are verified on the owner's bench (Task 9). Do not claim live behavior works without a bench run.
- **Suite is flaky** (~53 pre-existing failures); prove no-regression by diffing failed test IDs vs the base commit, not counts (see `test-suite-flaky-preexisting-failures` memory).

---

## File Structure

- **Create** `src/artisanlib/roest_device.py` — the codec (pure functions) + `class Roest(AsyncComm)`. One responsibility: everything Roest-USB-protocol. ~230 lines.
- **Create** `src/test/unitary/artisanlib/test_roest_codec.py` — unit tests for the ported pure codec (deframe/decode/encode). Hardware-independent.
- **Modify** `src/artisanlib/canvas.py` — devices list (#201-204), id-keyed registries, `OnMonitor`/`OffMonitorCloseDown` connect/disconnect, extra-device meter mappings.
- **Modify** `src/artisanlib/comm.py` — `devicefunctionlist` entries + `Roest_*` reader methods.
- **Modify** `src/artisanlib/devices.py` — `DeviceDlg.okEvent` Roest branch + serial defaults + Ports/config tab if needed.
- **Modify** `src/artisanlib/main.py` — `aw.roest` state + `roestSendMessageSignal`/slot + `eventaction` action-6 `roest(...)` branch.

Device ids (append after `+Orbiter Air/RoR` #200, which currently has **no trailing comma**): **#201 `Roest BT/ET`** (main), **#202 `+Roest Heat/Fan`**, **#203 `+Roest RPM/Drum`**, **#204 `+Roest Inlet/Target`** (extras; pairing confirm on bench).

---

### Task 1: Port the pure Roest USB codec into `roest_device.py`

**Files:**
- Create: `src/artisanlib/roest_device.py`
- Test: `src/test/unitary/artisanlib/test_roest_codec.py`

**Interfaces:**
- Produces: module-level `MAGIC=b'\xA5\x5A'`, `RECORD_LEN=22`, `FRAME_LEN=25`; `decode_record(b: bytes) -> dict[str, Any]`; `deframe(buf: bytearray) -> Iterator[bytes]`; control `CTRL_MAGIC=b'\x5A\xA5'`, `CTRL_REPEAT=8`, `clamp(chan:str, value:float) -> float`, `encode(chan:str, value:int) -> bytes`, `encode_power(pct:float) -> bytes`.

- [ ] **Step 1: Write the failing test** — `src/test/unitary/artisanlib/test_roest_codec.py`

```python
import struct
from artisanlib.roest_device import (
    MAGIC, RECORD_LEN, FRAME_LEN, decode_record, deframe,
    clamp, encode, encode_power, CTRL_MAGIC,
)


def _rec(bt=2150, et=1980, drum=0xFFFF, inlet=0xFFFF, target=0xFFFF,
         rtd2=0xFFFF, rtd3=0xFFFF, pcb=40, msec_units=5, phase=1,
         crack=0, heat=55.0, rpm=42, fan=60) -> bytes:
    b = bytearray(RECORD_LEN)
    struct.pack_into('<7H', b, 0, bt, et, rtd2, rtd3, drum, inlet, target)
    b[0x0E] = pcb
    b[0x0F] = 0
    struct.pack_into('<H', b, 0x10, (msec_units & 0x1FFF) | ((phase & 3) << 14))
    packed = (crack & 0xFF) | ((int(heat * 10) & 0x3FF) << 8) | ((rpm & 0x7F) << 18) | ((fan & 0x7F) << 25)
    struct.pack_into('<I', b, 0x12, packed)
    return bytes(b)


def _frame(rec: bytes) -> bytes:
    x = 0
    for c in rec:
        x ^= c
    return MAGIC + rec + bytes([x])


def test_decode_record_scales_and_none_sentinel():
    d = decode_record(_rec(bt=2150, et=1980, drum=0xFFFF))
    assert d['bt'] == 21.5
    assert d['et'] == 19.8
    assert d['drum_temp'] is None          # 0xFFFF -> absent
    assert d['phase'] == 1
    assert d['heat'] == 55.0
    assert d['rpm'] == 42
    assert d['fan'] == 60


def test_decode_record_wrong_length_raises():
    try:
        decode_record(b'\x00' * 10)
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_deframe_extracts_valid_record_and_resyncs_on_noise():
    rec = _rec()
    buf = bytearray(b'\x00\x11' + _frame(rec) + b'\xA5')  # leading noise + one frame + trailing partial magic
    out = list(deframe(buf))
    assert out == [rec]
    assert bytes(buf) == b'\xA5'                          # trailing partial magic byte kept


def test_deframe_drops_bad_xor_and_resyncs():
    rec = _rec()
    bad = MAGIC + rec + bytes([0x00])                     # wrong xor
    buf = bytearray(bad + _frame(rec))
    out = list(deframe(buf))
    assert out == [rec]                                   # bad frame skipped, good one recovered


def test_clamp_ranges():
    assert clamp('drum', 10) == 20 and clamp('drum', 99) == 65
    assert clamp('fan', 10) == 30 and clamp('fan', 999) == 100
    assert clamp('power', 250) == 100 and clamp('power', -5) == 0


def test_encode_drum_fan_5byte_xor():
    m = encode('drum', 40)
    assert m == CTRL_MAGIC + bytes([0x44, 40, 0x44 ^ 40])
    m = encode('fan', 60)
    assert m == CTRL_MAGIC + bytes([0x46, 60, 0x46 ^ 60])


def test_encode_power_8byte_float_xor():
    m = encode_power(50.0)                                # 50% -> frac 0.5
    assert len(m) == 8 and m[:2] == CTRL_MAGIC and m[2] == 0x50
    frac = struct.unpack('<f', m[3:7])[0]
    assert abs(frac - 0.5) < 1e-6
    x = 0x50
    for c in m[3:7]:
        x ^= c
    assert m[7] == x
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && python3 -m pytest test/unitary/artisanlib/test_roest_codec.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'artisanlib.roest_device'`

- [ ] **Step 3: Create `roest_device.py` with the ported codec** (top of the file; the `Roest` class is added in Task 2)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src && python3 -m pytest test/unitary/artisanlib/test_roest_codec.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/artisanlib/roest_device.py src/test/unitary/artisanlib/test_roest_codec.py
git commit -m "feat(roest): port Roest USB telemetry+control codec (pure, unit-tested)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `class Roest(AsyncComm)` — reader, getters, control

**Files:**
- Modify: `src/artisanlib/roest_device.py` (append the class after the codec)
- Test: `src/test/unitary/artisanlib/test_roest_codec.py` (add a `read_msg` streaming test)

**Interfaces:**
- Consumes: Task 1 codec (`MAGIC`, `RECORD_LEN`, `decode_record`, `encode`, `encode_power`, `CTRL_REPEAT`); `AsyncComm` base.
- Produces: `class Roest(AsyncComm)` with getters `getET()/getBT()/getHeat()/getFan()/getRPM()/getDrumTemp()/getInletTemp()/getTarget()` (all `-> float`, `-1` when absent), `send_msg(chan:str, value:float) -> None`, and event handlers wired through `__init__(serial, connected_handler, disconnected_handler, charge_handler, dry_handler, fcs_handler, drop_handler)`.

- [ ] **Step 1: Write the failing test** (append)

```python
import asyncio
from artisanlib.roest_device import Roest


class _FakeStream:
    # minimal asyncio.StreamReader stand-in: readuntil(sep)/readexactly(n) over a fixed buffer
    def __init__(self, data: bytes):
        self._d = bytearray(data)

    async def readuntil(self, sep: bytes) -> bytes:
        i = self._d.find(sep)
        if i < 0:
            raise asyncio.IncompleteReadError(bytes(self._d), None)
        end = i + len(sep)
        out = bytes(self._d[:end]); del self._d[:end]; return out

    async def readexactly(self, n: int) -> bytes:
        if len(self._d) < n:
            raise asyncio.IncompleteReadError(bytes(self._d), n)
        out = bytes(self._d[:n]); del self._d[:n]; return out


def test_roest_read_msg_populates_getters():
    rec = _rec(bt=2150, et=1980, heat=55.0, fan=60, rpm=42)
    r = Roest(serial=None)
    stream = _FakeStream(b'\x00noise' + _frame(rec))
    asyncio.get_event_loop().run_until_complete(r.read_msg(stream))
    assert r.getBT() == 21.5
    assert r.getET() == 19.8
    assert r.getHeat() == 55.0
    assert r.getFan() == 60
    assert r.getRPM() == 42


def test_roest_send_msg_bursts_control(monkeypatch):
    r = Roest(serial=None)
    sent = []
    monkeypatch.setattr(r, 'send', lambda b: sent.append(b))
    r.send_msg('drum', 40)
    assert sent and sent[0] == encode('drum', 40) * 8       # 8x burst
    sent.clear()
    r.send_msg('power', 50.0)
    assert sent[0] == encode_power(50.0) * 8
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd src && python3 -m pytest test/unitary/artisanlib/test_roest_codec.py -q -k "read_msg or send_msg"`
Expected: FAIL — `Roest` not defined / `read_msg` missing.

- [ ] **Step 3: Append the `Roest` class** to `roest_device.py`

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd src && python3 -m pytest test/unitary/artisanlib/test_roest_codec.py -q`
Expected: PASS (all)

- [ ] **Step 5: Verify import clean + commit**

```bash
cd src && python3 -c "import sys; from PyQt6.QtWidgets import QApplication; QApplication(sys.argv); import artisanlib.roest_device; print('ok')"
git add src/artisanlib/roest_device.py src/test/unitary/artisanlib/test_roest_codec.py
git commit -m "feat(roest): Roest(AsyncComm) device — streaming reader, getters, control burst

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Register the device (names, ids, registries)

**Files:**
- Modify: `src/artisanlib/canvas.py` — devices list end at `:1000` (`+Orbiter Air/RoR` #200), plus id registries near `:1043-1170`, `generateNoneTempHints()` `:13181`.

**Interfaces:**
- Produces: device ids `Roest BT/ET`=**201**, `+Roest Heat/Fan`=**202**, `+Roest RPM/Drum`=**203**, `+Roest Inlet/Target`=**204** referenced by all later tasks.

- [ ] **Step 1: Add the names to the devices list.** The last entry currently has NO trailing comma — add one, then append. Anchor (`canvas.py:1000`):

```python
                       '+Orbiter Air/RoR'            #200
                       ]
```
becomes
```python
                       '+Orbiter Air/RoR',           #200
                       'Roest BT/ET',                #201
                       '+Roest Heat/Fan',            #202
                       '+Roest RPM/Drum',            #203
                       '+Roest Inlet/Target'         #204
                       ]
```

- [ ] **Step 2: Add id 201 to the same non-Phidget/non-program groupings Santoker #134 is in.** Mirror each list where `134,` appears (`canvas.py:1065`, and the meter/serial groupings `:1043-1170`). For each `134, # Santoker BT/ET` membership that applies to a plain serial device, add `201, # Roest BT/ET`. Extras 202-204 mirror `135/136` (`+Santoker Power/Fan`, `+Santoker Drum`) memberships at `:1123-1124`, `:1147`.

- [ ] **Step 3: Add None-temp hints** so out-of-range extras render blank. In `generateNoneTempHints()` (`canvas.py:13181`), extend the hint set the same way the other extra-only devices do for 202-204 (heat/fan/rpm/drum/inlet/target are always-present numbers except when the sensor is absent → `-1`). Follow the existing pattern in that method for extra devices.

- [ ] **Step 4: Import + smoke.** `cd src && python3 -c "import sys; from PyQt6.QtWidgets import QApplication; QApplication(sys.argv); import artisanlib.main; print('devices', len(__import__('artisanlib.canvas',fromlist=['tgraphcanvas'])))"` — expect no error. (Full device-count assertion happens in Task 5's reader-list length check.)

- [ ] **Step 5: Commit**

```bash
git add src/artisanlib/canvas.py
git commit -m "feat(roest): register Roest device ids 201-204 + registries

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `aw` state + device-dialog selection + serial defaults

**Files:**
- Modify: `src/artisanlib/main.py` — `aw.roest` state near the Santoker block (`:1861`), `__slots__`/persisted-settings list (`:1514`).
- Modify: `src/artisanlib/devices.py` — `DeviceDlg.okEvent` branch (mirror the Santoker `elif meter==...` at the audit's `devices.py:3453/4234`) + serial defaults (`:4515`).

**Interfaces:**
- Consumes: device id 201 (Task 3), `Roest` class (Task 2).
- Produces: `aw.roest: Roest|None`, `aw.roestEventFlags: list[bool]`; selecting "Roest BT/ET" sets `aw.qmc.device=201` and serial defaults 115200 8N1.

- [ ] **Step 1: Add `aw` state** in `ApplicationWindow.__init__` next to the Santoker state (`main.py:1861`):

```python
        # Roest (native USB)
        self.roest:Roest|None = None # holds the Roest instance created on connect; reset to None on disconnect
        self.roestEventFlags:list[bool] = [False, False, False, False, False, False, False] # CHARGE, DRY, FCs, FCe, SCs, SCe, DROP
```
Add `Roest` to the `TYPE_CHECKING` import block (`main.py:174`): `from artisanlib.roest_device import Roest`. Add `'roest'`, `'roestEventFlags'` to the `__slots__`/settings list at `main.py:1514` next to `'santoker'`.

- [ ] **Step 2: Device-dialog selection.** In `DeviceDlg.okEvent` add a branch mirroring the Santoker one (the audit's `devices.py:4234`), setting `self.aw.qmc.device = 201` and the same serial defaults Santoker's serial mode uses (115200,8,'N',1,timeout). Read the Santoker branch first and copy-adapt it, substituting device id 201 and Roest naming. Put "Roest BT/ET" in the device dropdown list the dialog builds from `tgraphcanvas.devices` (it appears automatically as a non-`+`/`-` name).

- [ ] **Step 3: Serial defaults.** At `devices.py:4515` (serial-defaults table keyed by id), add `201: (115200, 8, 'N', 1)` mirroring Santoker's serial entry.

- [ ] **Step 4: Verify** the dialog builds: launch, open Config ▸ Device, confirm "Roest BT/ET" is selectable and selecting it stores device 201. (Bench-adjacent but no roaster needed — the dialog runs without hardware.)

- [ ] **Step 5: Commit**

```bash
git add src/artisanlib/main.py src/artisanlib/devices.py
git commit -m "feat(roest): device-dialog selection + aw.roest state + serial defaults

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `comm.py` reader methods + `devicefunctionlist`

**Files:**
- Modify: `src/artisanlib/comm.py` — `devicefunctionlist` (`:512` area) + new `Roest_*` methods (after `Santoker_D` at `:2064`).
- Test: `src/test/unitary/artisanlib/test_comm.py` (assert the id→method binding + tuple shape with a fake `aw.roest`).

**Interfaces:**
- Consumes: `aw.roest` getters (Task 2), device ids 201-204 (Task 3).
- Produces: `serialport.Roest_BTET/Roest_HF/Roest_RD/Roest_IT` returning `(tx, t1, t2)`; `devicefunctionlist[201..204]` bound.

- [ ] **Step 1: Write the failing test** (`test_comm.py`)

```python
def test_roest_reader_tuple(monkeypatch):
    import artisanlib.comm as comm
    # build a serialport with a fake aw.roest exposing the getters
    sp = _make_serialport()  # existing helper in this test module; or minimal stub with aw.qmc.timeclock + aw.roest
    class _R:
        def getET(self): return 198.0
        def getBT(self): return 215.0
        def getHeat(self): return 55.0
        def getFan(self): return 60.0
    sp.aw.roest = _R()
    sp.aw.qmc.mode = 'C'
    tx, t1, t2 = sp.Roest_BTET()
    assert (t1, t2) == (198.0, 215.0)      # t1=ET, t2=BT
    tx, h, f = sp.Roest_HF()
    assert (h, f) == (55.0, 60.0)
```
(If `test_comm.py` has no serialport helper, add a minimal one that sets `aw.qmc.timeclock.elapsedMilli` and `aw.qmc.mode`, mirroring the existing Santoker reader tests if present.)

- [ ] **Step 2: Run to verify it fails** — `cd src && python3 -m pytest test/unitary/artisanlib/test_comm.py -q -k roest` → FAIL (`Roest_BTET` missing).

- [ ] **Step 3: Add reader methods** after `Santoker_D` (`comm.py:2064`), mirroring `Santoker_BTET`/`Santoker_PF`:

```python
    def Roest_BTET(self) -> tuple[float,float,float]:
        tx = self.aw.qmc.timeclock.elapsedMilli()
        if self.aw.roest is not None:
            t1 = self.aw.roest.getET()
            t2 = self.aw.roest.getBT()
            if self.aw.qmc.mode == 'F':
                t1 = fromCtoFstrict(t1)
                t2 = fromCtoFstrict(t2)
        else:
            t1 = t2 = -1
        return tx,t1,t2 # time, ET (chan2), BT (chan1)

    def Roest_HF(self) -> tuple[float,float,float]:
        tx = self.aw.qmc.timeclock.elapsedMilli()
        if self.aw.roest is not None:
            t1 = self.aw.roest.getHeat()
            t2 = self.aw.roest.getFan()
        else:
            t1 = t2 = -1
        return tx,t1,t2 # time, Heat% (chan2), Fan% (chan1)

    def Roest_RD(self) -> tuple[float,float,float]:
        tx = self.aw.qmc.timeclock.elapsedMilli()
        if self.aw.roest is not None:
            t1 = self.aw.roest.getRPM()
            t2 = self.aw.roest.getDrumTemp()
            if self.aw.qmc.mode == 'F':
                t2 = fromCtoFstrict(t2)
        else:
            t1 = t2 = -1
        return tx,t1,t2 # time, RPM (chan2), Drum temp (chan1)

    def Roest_IT(self) -> tuple[float,float,float]:
        tx = self.aw.qmc.timeclock.elapsedMilli()
        if self.aw.roest is not None:
            t1 = self.aw.roest.getInletTemp()
            t2 = self.aw.roest.getTarget()
            if self.aw.qmc.mode == 'F':
                t1 = fromCtoFstrict(t1)
                t2 = fromCtoFstrict(t2)
        else:
            t1 = t2 = -1
        return tx,t1,t2 # time, Inlet temp (chan2), Target (chan1)
```

- [ ] **Step 4: Bind into `devicefunctionlist`.** The list is index-keyed by device id and must have entries for every id up to 204. After the last current entry (id 200), append `self.Roest_BTET, #201`, `self.Roest_HF, #202`, `self.Roest_RD, #203`, `self.Roest_IT, #204` (matching the devices-list order). Verify the list length now equals `len(tgraphcanvas.devices)+1` (the `ADD DEVICE:` invariant at `comm.py:375`).

- [ ] **Step 5: Run tests + assert length invariant, commit**

Run: `cd src && python3 -m pytest test/unitary/artisanlib/test_comm.py -q -k roest` → PASS
```bash
git add src/artisanlib/comm.py src/test/unitary/artisanlib/test_comm.py
git commit -m "feat(roest): comm reader methods + devicefunctionlist entries 201-204

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Connect on ON / disconnect on OFF

**Files:**
- Modify: `src/artisanlib/canvas.py` — `OnMonitor` `ADD DEVICE:` block (mirror Santoker `:13434-13458`) and `OffMonitorCloseDown` (mirror `:13643-13646`).

**Interfaces:**
- Consumes: `Roest` (Task 2), `aw.roest`/`aw.roestEventFlags` (Task 4), device id 201.
- Produces: on ON with device 201, `aw.roest` is created on the USB serial port and `.start()`ed; on OFF it is `.stop()`ed and set to None. Event handlers wired to the mark signals (bodies land in Task 8; wire them now to no-op-safe lambdas guarded by `roestEventFlags` exactly like Santoker).

- [ ] **Step 1: Add the connect block** in `OnMonitor` next to the Santoker block (`canvas.py:13434`). Auto-pick the USB port when the configured one is absent (name drift), mirroring `resolve_port` from the bridge:

```python
                elif self.device == 201:
                    # connect Roest (native USB)
                    import glob
                    from artisanlib.roest_device import Roest
                    from artisanlib.atypes import SerialSettings
                    port = self.aw.ser.comport
                    if not port or not __import__('os').path.exists(port):
                        found = sorted(glob.glob('/dev/tty.usbmodem*'))
                        port = found[0] if found else port
                    roest_serial = SerialSettings(port=port, baudrate=115200, bytesize=8,
                        stopbits=1, parity='N', timeout=self.aw.ser.timeout,
                        clear_HUPCL=False)
                    self.aw.roest = Roest(serial=roest_serial,
                        connected_handler=lambda : self.aw.sendmessageSignal.emit(QApplication.translate('Message', '{} connected').format('Roest'),True,None),
                        disconnected_handler=lambda : self.aw.sendmessageSignal.emit(QApplication.translate('Message', '{} disconnected').format('Roest'),True,None),
                        charge_handler=lambda : (self.markChargeDelaySignal.emit(0) if (len(self.aw.roestEventFlags)>0 and self.aw.roestEventFlags[0] and self.timeindex[0] == -1) else None),
                        dry_handler=lambda : (self.markDRYSignal.emit(False) if (len(self.aw.roestEventFlags)>1 and self.aw.roestEventFlags[1] and self.timeindex[1] == 0) else None),
                        fcs_handler=lambda : (self.markFCsSignal.emit(False) if (len(self.aw.roestEventFlags)>2 and self.aw.roestEventFlags[2] and self.timeindex[2] == 0) else None),
                        drop_handler=lambda : (self.markDropSignal.emit(False) if (len(self.aw.roestEventFlags)>6 and self.aw.roestEventFlags[6] and self.timeindex[6] == 0) else None))
                    self.aw.roest.setLogging(self.device_logging)
                    self.aw.roest.start()
```
(Confirm the exact `SerialSettings` TypedDict fields against `atypes.py` and the Santoker construction at `canvas.py:13438` — copy that field set exactly.)

- [ ] **Step 2: Add the disconnect block** in `OffMonitorCloseDown` next to Santoker (`canvas.py:13643`):

```python
                # disconnect Roest
                if not bool(self.aw.simulator) and self.device == 201 and self.aw.roest is not None:
                    self.aw.roest.stop()
                    self.aw.roest = None
```

- [ ] **Step 3: Import smoke** — `cd src && python3 -c "import sys; from PyQt6.QtWidgets import QApplication; QApplication(sys.argv); import artisanlib.canvas; print('ok')"` → no error.

- [ ] **Step 4: Commit**

```bash
git add src/artisanlib/canvas.py
git commit -m "feat(roest): connect on ON / disconnect on OFF (mirrors Santoker)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Control out — `roest(<chan>,<value>)` event action

**Files:**
- Modify: `src/artisanlib/main.py` — `roestSendMessageSignal` + connect (`:1477`/`:4352` analogs), `eventaction` action-6 branch (`:9676` analog), and the `roestSendMessage` slot (Santoker's slot at the audit's `main.py:18174`).

**Interfaces:**
- Consumes: `aw.roest.send_msg` (Task 2).
- Produces: an `eventaction`/IO-command string `roest(drum,40)` / `roest(fan,60)` / `roest(power,50)` drives `aw.roest.send_msg(chan, value)` via a Qt signal (thread-safe). A `roest(drop,…)` token is parsed but **ignored with a log line** (P4 not wired).

- [ ] **Step 1: Declare + connect the signal.** Next to `santokerSendMessageSignal = pyqtSignal(bytes,int)` (`main.py:1477`) add `roestSendMessageSignal = pyqtSignal(str,float)`. Next to `self.santokerSendMessageSignal.connect(self.santokerSendMessage)` (`main.py:4352`) add `self.roestSendMessageSignal.connect(self.roestSendMessage)`.

- [ ] **Step 2: Add the slot** (mirror `santokerSendMessage`, the audit's `main.py:18174`):

```python
    @pyqtSlot(str,float)
    def roestSendMessage(self, chan:str, value:float) -> None:
        if self.roest is not None:
            try:
                self.roest.send_msg(chan, value)
            except Exception as e: # pylint: disable=broad-except
                _log.exception(e)
```

- [ ] **Step 3: Parse the command** in `eventaction` action `6` next to the `santoker(...)` branch (`main.py:9676`). Accept `roest(<chan>,<value>)` where chan ∈ {drum,fan,power}; emit `roestSendMessageSignal`. A `drop`/unknown chan logs and returns (P4 slot, not wired):

```python
                                elif c.startswith('roest'):
                                    try:
                                        args = c[c.index('(')+1:c.rindex(')')].split(',')
                                        chan = args[0].strip().lower()
                                        if chan in ('drum','fan','power'):
                                            self.roestSendMessageSignal.emit(chan, float(args[1]))
                                        else:
                                            _log.info('roest(%s) ignored (not wired / unsafe)', chan)
                                    except Exception as e: # pylint: disable=broad-except
                                        _log.exception(e)
```
(Also add the `##  roest(<chan>,<value>)` doc line next to the santoker one at `main.py:9496/9675`.)

- [ ] **Step 4: Unit-test the parse→signal path** (`test/unitary/artisanlib/test_command_utility.py` or a new small test): feed `eventaction`-style strings and assert the emitted `(chan,value)` for drum/fan/power and that `roest(drop,1)` emits nothing. Use a stub `aw` capturing `roestSendMessageSignal.emit`. If wiring a full `eventaction` test is heavy, unit-test a small extracted parser helper instead (`_parse_roest_command(c) -> tuple[str,float]|None`) and call it from the branch.

- [ ] **Step 5: Commit**

```bash
git add src/artisanlib/main.py src/test/unitary/artisanlib/test_command_utility.py
git commit -m "feat(roest): control out via eventaction roest(chan,value) (drop slot left unwired)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Roast event auto-marks from telemetry (HARDWARE-GATED mapping)

**Files:**
- Modify: `src/artisanlib/roest_device.py` — event emission in `register_reading` (rising-edge, mirrors `Santoker.register_reading`).
- Test: `src/test/unitary/artisanlib/test_roest_codec.py` — assert rising-edge handler firing for a GIVEN mapping.

**Interfaces:**
- Consumes: `rec['phase']`, `rec['crack']` (Task 1 decode), the `*_handler` callbacks (Task 2).
- Produces: `charge_handler/dry_handler/fcs_handler/drop_handler` fire once each on the confirmed transition.

> **BLOCKED until the bench (Task 9) confirms the exact `phase`/`crack` → event mapping.** The ported codec exposes `phase` (0-3, 2 bits) and `crack` (u8) but the audit does not pin how they encode CHARGE/DRY/FC/DROP. Do NOT guess in shipped code. Land the *structure* now (rising-edge, guarded, one-shot) behind a single documented mapping function `_events_from(phase, crack)` and fill its body from the bench observation.

- [ ] **Step 1: Add a one-shot rising-edge emitter** to `register_reading` (structure mirrors Santoker `:251-290`): track previous `_charge/_dry/_fcs/_drop` booleans, and for each, when a decode function `self._is_charge(rec)`/`_is_dry`/`_is_fcs`/`_is_drop` goes True on the rising edge, call the handler once (wrapped in try/except). Provide the mapping stubs returning `False` with a `# BENCH: confirm mapping` comment so nothing fires until filled.
- [ ] **Step 2: Write tests** that inject a synthetic record sequence and assert each handler fires exactly once on its transition — using the mapping the bench confirms (write the test against the confirmed rule, then implement the mapping to match).
- [ ] **Step 3: Fill the mapping** from the bench recording (Task 9 produces a labeled telemetry capture: roast with known CHARGE/DRY/FC/DROP timestamps → read `phase`/`crack` at those points).
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** `feat(roest): drive Artisan roast marks from telemetry phase/crack`.

---

### Task 9: Bench bring-up + validation (owner hardware) — NOT automatable here

**Files:** none (a checklist; findings feed Task 8's mapping and confirm Task 3's channel pairing).

This is the only way to validate live behavior — there is no Roest in the build environment. Run on the owner's bench with the roaster on USB:

- [ ] **Connect:** Config ▸ Device ▸ "Roest BT/ET"; set the serial port (or rely on the `/dev/tty.usbmodem*` auto-pick). Press ON. Expect "Roest connected" and BT/ET tracking.
- [ ] **Channel mapping:** confirm temp1=ET, temp2=BT read correctly and extras (heat/fan/rpm/drum_temp/inlet_temp/target) land on the intended #202-204 rows; adjust the pairing in Task 3/Task 5 if the roaster's channels differ.
- [ ] **Events:** run a roast; note wall-clock CHARGE/DRY/FC/DROP; capture telemetry (`setLogging(True)`) and read `phase`/`crack` at each; encode the mapping into Task 8's `_events_from` + tests.
- [ ] **Control:** set drum/fan/power via the Artisan sliders/`eventaction` `roest(...)`; confirm the roaster responds and the 8× burst is reliable.
- [ ] **DROP (P4):** leave unwired — do not test Artisan→roaster DROP until the firmware side lands a non-blocking dropper trigger.
- [ ] **Regression + release:** full-suite no-regression (diff failed IDs vs base); then merge `--no-ff` and release per the pipeline (`release-and-autoupdate-pipeline` memory).

---

## Self-Review

**Spec coverage:** Option A recommendation → Tasks 1-8. Codec reuse → Task 1/2. `ADD DEVICE:` seams → Tasks 3-7 (name/id, dialog, reader, connect/disconnect, control). Events auto-mark → Task 8. Channel mapping + live validation → Task 9. P4 DROP left unwired → Global Constraints + Task 7/9. All audit points mapped.

**Placeholder scan:** the only deliberately-deferred body is Task 8's `_events_from` mapping — this is not a placeholder-by-omission; it is a hard external dependency (bench observation) called out explicitly with a gating note, per the audit's "roaster auto-detects … confirm on integration." Everything build-time is concrete code.

**Type consistency:** `Roest.send_msg(chan:str, value:float)` matches the `roestSendMessageSignal = pyqtSignal(str,float)` and the `roestSendMessage(self, chan:str, value:float)` slot (Tasks 2/7). Getters return `float` and the readers pass them straight into the `(tx,t1,t2)` tuple (Tasks 2/5). Device ids 201-204 are used identically in Tasks 3/4/5/6.
