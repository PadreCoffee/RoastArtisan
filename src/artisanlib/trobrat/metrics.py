#!/usr/bin/env python3
"""Read-only Trobrat S7-1200 symbolic telemetry -> local read-only Modbus TCP.

No third-party dependencies. No PLC writes, controls, scans, or program transfers.
Selectors are specific to the verified PLC program and capture.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
from logging.handlers import RotatingFileHandler
import math
from pathlib import Path
import socket
import socketserver
import struct
import threading
import time
from typing import cast, override

LOG = logging.getLogger("trobrat")
PLC_HOST = "192.168.0.1"
MODBUS_HOST = "127.0.0.1"
MODBUS_PORT = 15020
# Captured successful COTP CR, including source TSAP 0200 / destination 0201.
COTP_CONNECT = bytes.fromhex("0300001611e00001000100c1020200c2020201c0010a")
SETUP_PARAMETER = bytes.fromhex("f0000001000300f0")


class ProtocolError(Exception):
    pass


@dataclass(frozen=True)
class Metric:
    key: str
    tag: str
    register: int
    area1: int
    area2_or_db: int
    crc: int
    lids: tuple[tuple[int, int], ...]
    kind: str = "real"

    def selector(self) -> bytes:
        body = struct.pack(">BBHHI", 0xB2, 0xFF, self.area1,
                           self.area2_or_db, self.crc)
        body += b"".join(struct.pack(">I", flag << 28 | value)
                         for flag, value in self.lids)
        return bytes((0x12, len(body))) + body


METRICS = (
    Metric("gas_mbar", "MArea-GasPressure", 0, 0, 0x52, 0xF9DE76BF, ((4, 86),)),
    Metric("air_pa", "AirPressure[DB18]-Q", 2, 0x8A0E, 18, 0xF1B01A54, ((2, 10), (4, 9))),
    Metric("drum_active_rpm", "MArea-M1:ActSp", 4, 0, 0x52, 0x42DD87E0, ((4, 95),)),
    Metric("air_pid_output_rpm", "MArea-PID_AirPressureOut_rpm", 6, 0, 0x52, 0xC99F131B, ((4, 79),)),
    Metric("gas_active_sp_mbar", "MArea-PID_Gas:ActSp", 8, 0, 0x52, 0xBCB46198, ((4, 99),)),
    Metric("burner_output_percent", "MArea-Burner:SP", 10, 0, 0x52, 0x70F529A1, ((4, 61),)),
    Metric("burner_output_on", "QArea-Burner:D", 12, 0, 0x51, 0xF58BEC74, ((4, 17),), "bit"),
    Metric("bt_c", "MArea-TE1:R", 14, 0, 0x52, 0xF8DB151F, ((4, 18),)),
    Metric("et_c", "MArea-TE2:R", 16, 0, 0x52, 0x670CAF5A, ((4, 22),)),
    Metric("air_sp_pa", "HMI_PIDAir[DB24]-SP", 18, 0x8A0E, 24, 0x590EF01D, ((4, 17),)),
)


def tpkt(payload: bytes) -> bytes:
    return struct.pack(">BBH", 3, 0, len(payload) + 4) + payload


def make_job(function: int, reference: int, metrics: tuple[Metric, ...] = ()) -> bytes:
    # Deliberately no generic function/pass-through interface.
    if function == 0xF0 and not metrics:
        parameter = SETUP_PARAMETER
    elif function == 4 and metrics:
        if not all(m in METRICS for m in metrics):
            raise ValueError("Only the verified telemetry selectors are allowed")
        parameter = bytes((4, len(metrics))) + b"".join(m.selector() for m in metrics)
    else:
        raise ValueError("Only Setup Communication and ReadVar are implemented")
    s7 = struct.pack(">BBHHHH", 0x32, 1, 0, reference, len(parameter), 0) + parameter
    return tpkt(b"\x02\xf0\x80" + s7)


def read_exact(sock: socket.socket, count: int) -> bytes:
    parts = bytearray()
    while len(parts) < count:
        part = sock.recv(count - len(parts))
        if not part:
            raise ProtocolError("Connection closed by peer")
        parts.extend(part)
    return bytes(parts)


def receive_tpkt(sock: socket.socket) -> bytes:
    header = read_exact(sock, 4)
    version, reserved, length = struct.unpack(">BBH", header)
    if (version, reserved) != (3, 0) or not 7 <= length <= 8192:
        raise ProtocolError("Invalid TPKT header/length")
    return read_exact(sock, length - 4)


def receive_s7(sock: socket.socket) -> bytes:
    result = bytearray()
    for _ in range(16):
        packet = receive_tpkt(sock)
        if packet[:2] != b"\x02\xf0":
            raise ProtocolError("Unexpected COTP packet")
        result.extend(packet[3:])
        if len(result) > 8192:
            raise ProtocolError("S7 PDU too large")
        if packet[2] & 0x80:
            return bytes(result)
    raise ProtocolError("Too many COTP fragments")


def split_ack(s7: bytes, reference: int, function: int) -> tuple[bytes, bytes]:
    if len(s7) < 12:
        raise ProtocolError("Short S7 acknowledgement")
    protocol, rosctr, reserved, ref, plen, dlen = struct.unpack(">BBHHHH", s7[:10])
    if protocol != 0x32 or rosctr != 3 or reserved or ref != reference:
        raise ProtocolError("Unexpected S7 acknowledgement/reference")
    if s7[10:12] != b"\0\0":
        raise ProtocolError(f"PLC returned S7 error {s7[10:12].hex()}")
    if len(s7) != 12 + plen + dlen:
        raise ProtocolError("S7 acknowledgement length mismatch")
    parameter, data = s7[12:12 + plen], s7[12 + plen:]
    if not parameter or parameter[0] != function:
        raise ProtocolError("Unexpected S7 function in acknowledgement")
    return parameter, data


def parse_read_data(data: bytes, count: int) -> list[tuple[int, int, bytes]]:
    """Return ordered (return code, transport, raw data), preserving bit padding."""
    result = []
    offset = 0
    for index in range(count):
        if offset + 4 > len(data):
            raise ProtocolError("Short ReadVar item header")
        code, transport, length = struct.unpack(">BBH", data[offset:offset + 4])
        offset += 4
        size = (length + 7) // 8 if transport in (3, 4, 5) else length
        if offset + size > len(data):
            raise ProtocolError("Short ReadVar item payload")
        raw = data[offset:offset + size]
        offset += size
        result.append((code, transport, raw))
        if size % 2 and index < count - 1:
            if offset >= len(data) or data[offset] != 0:
                raise ProtocolError("Missing ReadVar padding")
            offset += 1
    if offset != len(data):
        raise ProtocolError("Unexpected trailing ReadVar bytes")
    return result


def decode_value(metric: Metric, item: tuple[int, int, bytes]) -> float:
    code, transport, raw = item
    if code != 0xFF:
        raise ProtocolError(f"{metric.key}: PLC item error 0x{code:02x}")
    if metric.kind == "real" and transport == 7 and len(raw) == 4:
        value = struct.unpack(">f", raw)[0]
        if math.isfinite(value):
            return float(value)
    if metric.kind == "bit" and transport == 3 and raw in (b"\0", b"\1"):
        return float(raw[0])
    raise ProtocolError(f"{metric.key}: unexpected/non-finite data type")


class S7Reader:
    def __init__(self, host: str = PLC_HOST, timeout: float = 2.0):
        self.host = host
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.reference = 0
        self.pdu_limit = 240

    def next_reference(self) -> int:
        self.reference = self.reference % 65535 + 1
        return self.reference

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def connect(self) -> None:
        self.close()
        try:
            self.sock = socket.create_connection((self.host, 102), self.timeout)
            self.sock.settimeout(self.timeout)
            self.sock.sendall(COTP_CONNECT)
            cc = receive_tpkt(self.sock)
            if len(cc) < 7 or cc[0] != len(cc) - 1 or cc[1] != 0xD0 or cc[2:4] != b"\0\1":
                raise ProtocolError("PLC did not confirm COTP connection")
            ref = self.next_reference()
            self.sock.sendall(make_job(0xF0, ref))
            parameter, data = split_ack(receive_s7(self.sock), ref, 0xF0)
            if len(parameter) != 8 or data:
                raise ProtocolError("Invalid Setup Communication acknowledgement")
            _, _, calling, called, pdu = struct.unpack(">BBHHH", parameter)
            if not calling or not called or pdu < 80:
                raise ProtocolError("Insufficient negotiated PDU size")
            self.pdu_limit = min(240, pdu)
        except Exception:
            self.close()
            raise

    def read(self, metrics: tuple[Metric, ...] = METRICS) -> tuple[dict[str, float], dict[str, str]]:
        if self.sock is None:
            raise ProtocolError("Not connected")
        ref = self.next_reference()
        request = make_job(4, ref, metrics)
        if len(request) - 7 > self.pdu_limit:
            raise ProtocolError("Read request exceeds negotiated PDU size")
        self.sock.sendall(request)
        parameter, data = split_ack(receive_s7(self.sock), ref, 4)
        if parameter != bytes((4, len(metrics))):
            raise ProtocolError("Read acknowledgement item count mismatch")
        items = parse_read_data(data, len(metrics))
        values, errors = {}, {}
        for metric, item in zip(metrics, items, strict=True):
            try:
                values[metric.key] = decode_value(metric, item)
            except ProtocolError as exc:
                errors[metric.key] = str(exc)
        return values, errors


class Readings:
    def __init__(self, stale_after: float = 4.0):
        self.lock = threading.Lock()
        self.stale_after = stale_after
        self.values: dict[str, tuple[float, float]] = {}
        self.errors: dict[str, str] = {}

    def update(self, values: dict[str, float], errors: dict[str, str]) -> None:
        now = time.monotonic()
        with self.lock:
            for key, value in values.items():
                self.values[key] = (value, now)
            for key in errors:
                self.values.pop(key, None)
            self.errors = dict(errors)

    def invalidate(self, reason: str) -> None:
        with self.lock:
            self.values.clear()
            self.errors = {"connection": reason}

    def snapshot(self) -> dict[str, dict[str, float | str | None]]:
        now = time.monotonic()
        with self.lock:
            return {m.key: {"value": self.values[m.key][0],
                            "age_seconds": round(now - self.values[m.key][1], 2)}
                    if m.key in self.values and now - self.values[m.key][1] <= self.stale_after
                    else {"value": None, "status": "unavailable"}
                    for m in METRICS}

    def registers(self, start: int, count: int) -> bytes:
        if not 1 <= count <= 125 or start < 0 or start + count > len(METRICS) * 2:
            raise ValueError("Unknown register range")
        now = time.monotonic()
        with self.lock:
            payload = bytearray()
            for index in range(start // 2, (start + count - 1) // 2 + 1):
                metric = METRICS[index]
                entry = self.values.get(metric.key)
                if entry is None or now - entry[1] > self.stale_after:
                    raise ProtocolError(f"{metric.key} unavailable/stale")
                payload.extend(struct.pack(">f", entry[0]))
            skip = (start % 2) * 2
            return bytes(payload[skip:skip + count * 2])


def modbus_pdu(pdu: bytes, unit: int, readings: Readings) -> bytes:
    function = pdu[0] if pdu else 0
    # No write function or forwarding of client requests exists.
    if function not in (3, 4):
        return bytes((function | 0x80, 1))
    if unit != 1 or len(pdu) != 5:
        return bytes((function | 0x80, 3))
    start, count = struct.unpack(">HH", pdu[1:])
    if not 1 <= count <= 125:
        return bytes((function | 0x80, 3))
    try:
        payload = readings.registers(start, count)
    except ValueError:
        return bytes((function | 0x80, 2))
    except ProtocolError:
        return bytes((function | 0x80, 4))
    return bytes((function, len(payload))) + payload


class ModbusHandler(socketserver.BaseRequestHandler):
    @override
    def handle(self) -> None:
        self.request.settimeout(10)
        try:
            while True:
                header = read_exact(self.request, 7)
                transaction, protocol, length, unit = struct.unpack(">HHHB", header)
                if protocol != 0 or not 2 <= length <= 254:
                    return
                pdu = read_exact(self.request, length - 1)
                server = cast('ModbusServer', self.server)
                reply = modbus_pdu(pdu, unit, server.readings)
                self.request.sendall(struct.pack(">HHHB", transaction, 0, len(reply) + 1, unit) + reply)
        except (OSError, ProtocolError):
            return


class ModbusServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, readings: Readings, port: int = MODBUS_PORT):
        self.readings = readings
        super().__init__((MODBUS_HOST, port), ModbusHandler)


def poll(stop: threading.Event, readings: Readings, host: str, interval: float) -> None:
    reader = S7Reader(host)
    previous_errors = None
    try:
        while not stop.is_set():
            try:
                if reader.sock is None:
                    reader.connect()
                    LOG.info("Connected to Siemens %s:102 (read only)", host)
                started = time.monotonic()
                values, errors = reader.read()
                readings.update(values, errors)
                if errors != previous_errors:
                    LOG.warning("Unavailable metrics: %s", errors) if errors else LOG.info("All 10 metrics available")
                    previous_errors = errors
                stop.wait(max(0, interval - (time.monotonic() - started)))
            except (OSError, ProtocolError) as exc:
                readings.invalidate(str(exc))
                reader.close()
                LOG.error("No fresh PLC data: %s. Retrying in 5 seconds.", exc)
                stop.wait(5)
    finally:
        reader.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true", help="Read one cycle, print metrics, exit")
    mode.add_argument("--serve", action="store_true", help="Poll once per second and serve local Modbus")
    mode.add_argument("--self-test", action="store_true", help="Run offline fixture and loopback tests, no PLC access")
    parser.add_argument("--host", default=PLC_HOST)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.self_test:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent / "tests"), pattern="test_*.py")
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    log_path = Path(__file__).resolve().parent / "trobrat-metrics.log"
    try:
        handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        LOG.info("Log: %s", log_path)
    except OSError as exc:
        LOG.warning("Cannot create log file: %s", exc)
    if args.probe:
        reader = S7Reader(args.host)
        try:
            reader.connect()
            values, errors = reader.read()
            LOG.info("Probe values: %s; errors: %s", json.dumps(values), json.dumps(errors))
            print(json.dumps({"values": values, "errors": errors}, ensure_ascii=False, indent=2))
            return 1 if errors else 0
        except (OSError, ProtocolError) as exc:
            LOG.error("Probe failed: %s", exc)
            return 1
        finally:
            reader.close()
    readings, stop = Readings(), threading.Event()
    try:
        server = ModbusServer(readings)
    except OSError as exc:
        LOG.error("Cannot listen on %s:%d: %s", MODBUS_HOST, MODBUS_PORT, exc)
        return 1
    threading.Thread(target=poll, args=(stop, readings, args.host, 1.0), daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    LOG.info("Local read-only Modbus TCP %s:%d, unit 1. Ctrl+C stops telemetry.", MODBUS_HOST, MODBUS_PORT)
    try:
        while not stop.wait(5):
            LOG.info("Telemetry %s", json.dumps(readings.snapshot(), ensure_ascii=False))
    except KeyboardInterrupt:
        LOG.info("Stopping telemetry")
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
