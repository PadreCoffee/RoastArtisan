import asyncio
import pytest
import struct
from artisanlib.roest_device import (
    MAGIC, RECORD_LEN, FRAME_PAYLOAD_LEN, decode_record, deframe,
    clamp, encode, encode_power, CTRL_MAGIC, Roest,
)


def _rec(bt=2150, et=1980, drum=0xFFFF, inlet=0xFFFF, target=0xFFFF,
         rtd2=0xFFFF, rtd3=0xFFFF, pcb=40, msec_units=5, phase=1,
         crack=0, heat=55.0, rpm=42, fan=60, state0=1) -> bytes:
    # returns the 23-byte frame payload: 22-byte ring record + trailing state0 (roast FSM) byte
    b = bytearray(RECORD_LEN)
    struct.pack_into('<7H', b, 0, bt, et, rtd2, rtd3, drum, inlet, target)
    b[0x0E] = pcb
    b[0x0F] = 0
    struct.pack_into('<H', b, 0x10, (msec_units & 0x1FFF) | ((phase & 3) << 14))
    packed = (crack & 0xFF) | ((int(heat * 10) & 0x3FF) << 8) | ((rpm & 0x7F) << 18) | ((fan & 0x7F) << 25)
    struct.pack_into('<I', b, 0x12, packed)
    b.append(state0 & 0xFF)
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
    assert d['rtd2'] is None
    assert d['rtd3'] is None
    assert d['inlet_temp'] is None
    assert d['target'] is None
    assert d['pcb_temperature'] == 40
    assert d['msec'] == 5000
    assert d['phase'] == 1
    assert d['crack'] == 0
    assert d['heat'] == 55.0
    assert d['rpm'] == 42
    assert d['fan'] == 60
    assert d['state0'] == 1                 # 23-byte payload -> state0 present


def test_decode_record_wrong_length_raises():
    with pytest.raises(ValueError):
        decode_record(b'\x00' * 10)


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


def test_deframe_extracts_multiple_records_in_one_call():
    r1 = _rec(bt=2000)
    r2 = _rec(bt=2100)
    buf = bytearray(_frame(r1) + _frame(r2))
    assert list(deframe(buf)) == [r1, r2]


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


class _FakeStream:
    # minimal asyncio.StreamReader stand-in: readuntil(sep)/readexactly(n) over a fixed buffer
    def __init__(self, data: bytes):
        self._d = bytearray(data)

    async def readuntil(self, sep: bytes) -> bytes:
        i = self._d.find(sep)
        if i < 0:
            raise asyncio.IncompleteReadError(bytes(self._d), None)
        end = i + len(sep)
        out = bytes(self._d[:end])
        del self._d[:end]
        return out

    async def readexactly(self, n: int) -> bytes:
        if len(self._d) < n:
            raise asyncio.IncompleteReadError(bytes(self._d), n)
        out = bytes(self._d[:n])
        del self._d[:n]
        return out


def test_roest_read_msg_populates_getters():
    rec = _rec(bt=2150, et=1980, heat=55.0, fan=60, rpm=42)
    r = Roest(serial=None)
    stream = _FakeStream(b'\x00noise' + _frame(rec))
    asyncio.run(r.read_msg(stream))
    assert r.getBT() == 21.5
    assert r.getET() == 19.8
    assert r.getHeat() == 55.0
    assert r.getFan() == 60
    assert r.getRPM() == 42


def test_roest_send_msg_bursts_control(monkeypatch):
    r = Roest(serial=None)
    sent = []
    monkeypatch.setattr(type(r), 'send', lambda _, b: sent.append(b))
    r.send_msg('drum', 40)
    assert sent and sent[0] == encode('drum', 40) * 8       # 8x burst
    sent.clear()
    r.send_msg('power', 50.0)
    assert sent[0] == encode_power(50.0) * 8


def _make_roest_with_handlers() -> tuple[Roest, list, list, list, list]:
    charges: list = []
    drys: list = []
    fcss: list = []
    drops: list = []
    r = Roest(serial=None,
               charge_handler=lambda: charges.append(True),
               dry_handler=lambda: drys.append(True),
               fcs_handler=lambda: fcss.append(True),
               drop_handler=lambda: drops.append(True))
    return r, charges, drys, fcss, drops


def test_rec_payload_is_23_bytes():
    assert len(_rec()) == FRAME_PAYLOAD_LEN


def test_decode_record_accepts_legacy_22_byte_record_without_state0():
    d = decode_record(_rec()[:RECORD_LEN])   # strip the state0 byte -> 22-byte legacy record
    assert d['state0'] is None


def test_state0_event_predicates():
    assert Roest._is_charge(5) and not Roest._is_charge(6)
    assert Roest._is_dry(6) and not Roest._is_dry(5)
    assert Roest._is_fcs(7) and not Roest._is_fcs(9)
    # DROP fires only when leaving 7 (prev==7 -> 9/10/4/1)
    assert Roest._is_drop(9, 7) and Roest._is_drop(10, 7) and Roest._is_drop(1, 7)
    assert not Roest._is_drop(9, 6)          # did not come from FC
    assert not Roest._is_drop(1, 1)          # plain idle, not a drop
    assert not Roest._is_charge(None) and not Roest._is_drop(9, None)


def test_register_reading_marks_charge_dry_fc_drop_from_state0():
    r, charges, drys, fcss, drops = _make_roest_with_handlers()
    # idle -> preheat -> CHARGE -> DRY -> FC -> DROP -> cooling
    for s in (1, 3, 5, 6, 7, 9, 10, 4, 1):
        r.register_reading(decode_record(_rec(state0=s)))
    assert len(charges) == 1
    assert len(drys) == 1
    assert len(fcss) == 1
    assert len(drops) == 1                    # fired once, on 7 -> 9


def test_register_reading_charge_fires_once_per_entry_into_5():
    r, charges, drys, fcss, drops = _make_roest_with_handlers()
    for s in (5, 5, 3, 5):                     # enter 5, stay, leave, re-enter
        r.register_reading(decode_record(_rec(state0=s)))
    assert len(charges) == 2                   # one per rising edge into 5
    assert drys == [] and fcss == [] and drops == []


def test_drop_fires_when_state0_leaves_7_even_if_9_skipped():
    r, _charges, _drys, _fcss, drops = _make_roest_with_handlers()
    for s in (7, 10):                          # slow USB read: transient 9 missed, 7 -> 10 directly
        r.register_reading(decode_record(_rec(state0=s)))
    assert len(drops) == 1


def test_no_false_events_when_state0_absent_legacy_fw():
    r, charges, drys, fcss, drops = _make_roest_with_handlers()
    for _ in range(5):
        r.register_reading(decode_record(_rec()[:RECORD_LEN]))   # state0 None
    assert charges == [] and drys == [] and fcss == [] and drops == []
