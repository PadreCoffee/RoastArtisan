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
