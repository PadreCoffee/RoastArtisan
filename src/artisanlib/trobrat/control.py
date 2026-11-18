#!/usr/bin/env python3
"""Verified Trobrat setpoint selectors -> local Artisan Modbus commands.

Positive gas SP can cause ignition/heat in a panel-enabled operating mode.
This client does not reproduce HMI validation or provide a safety controller.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
from logging.handlers import RotatingFileHandler
import math
from pathlib import Path
import socketserver
import struct
import threading
import time
from typing import cast, override

from . import metrics as core

LOG = logging.getLogger("trobrat-control")
DRUM_SP = core.Metric("drum_recipe_sp", "Recipe[DB20]-M1:SP", 100,
                      0x8A0E, 20, 0xB128DEF4, ((2, 29), (4, 9)))
AIR_SP = core.METRICS[9]
GAS_SP = core.Metric("gas_recipe_sp", "Act_Recipe[DB20]-PID_Gas:SP", 104,
                     0x8A0E, 20, 0xAC577633, ((4, 40),))
PROFILE_AUTO = core.Metric("profile_auto", "MArea-ProfileModeAuto", 0,
                           0, 0x52, 0x60409EB6, ((4, 97),), "bit")
ROAST_ON = core.Metric("roast_on", "MArea-RoastOn", 0,
                       0, 0x52, 0x41CF7976, ((4, 92),), "bit")
GAS_MODE = core.Metric("gas_pressure_mode", "Act_Recipe[DB20]-PID_Gas:Mode", 0,
                       0x8A0E, 20, 0x74A350EE, ((4, 41),), "int16")
AIR_MODE = core.Metric("air_pressure_mode", "HMI_PIDAir[DB24]-Mode", 0,
                       0x8A0E, 24, 0xF024FDB1, ((4, 10),), "int16")
ROSTER_ON = core.Metric("panel_run_command", "MArea-Roster:G", 0,
                        0, 0x52, 0x44C3F3D0, ((4, 27),), "bit")


@dataclass(frozen=True)
class Target:
    key: str
    metric: core.Metric
    register: int
    minimum: float
    maximum: float
    active_key: str | None
    measured_key: str | None


SETPOINT_TARGETS = (
    Target("drum", DRUM_SP, 100, 0.0, 65.0, "drum_active_rpm", None),
    Target("air", AIR_SP, 102, 0.0, 300.0, None, "air_pa"),
    Target("gas", GAS_SP, 104, 0.0, 20.0, "gas_active_sp_mbar", "gas_mbar"),
)
MIXER_GM = core.Metric("mixer_manual_command", "MArea-M3:GM", 106, 0, 0x52,
                       0x5E8E3EE0, ((4, 33),), "bit")
COOLER_GM = core.Metric("cooler_manual_command", "MArea-M4:GM", 108, 0, 0x52,
                        0xECC83CB4, ((4, 35),), "bit")
DESTONER_GM = core.Metric("destoner_manual_command", "MArea-M6:GM", 110, 0, 0x52,
                          0x042F0E56, ((4, 39),), "bit")
AUX_TARGETS = (
    Target("mixer", MIXER_GM, 106, 0, 1, None, None),
    Target("cooler", COOLER_GM, 108, 0, 1, None, None),
    Target("destoner", DESTONER_GM, 110, 0, 1, None, None),
)
TARGETS = SETPOINT_TARGETS + AUX_TARGETS
ALL_READS = core.METRICS + (DRUM_SP, GAS_SP, PROFILE_AUTO, ROAST_ON,
                          GAS_MODE, AIR_MODE, ROSTER_ON)
CONTEXT_READS = (DRUM_SP, AIR_SP, GAS_SP, PROFILE_AUTO, GAS_MODE, AIR_MODE,
                 ROSTER_ON, core.METRICS[2], core.METRICS[3],
                 core.METRICS[4], core.METRICS[6], core.METRICS[0], core.METRICS[1])
READ_KEYS = {m.key for m in core.METRICS}
PUBLISHED_KEYS = READ_KEYS | {t.metric.key for t in TARGETS}
ALLOWED_READS = ALL_READS + tuple(t.metric for t in AUX_TARGETS)


def context_for(target: Target) -> tuple[core.Metric, ...]:
    # New motor symbols are read only on explicit motor commands, so a failed
    # first M6 read cannot interrupt the already-tested pressure telemetry.
    return (PROFILE_AUTO, target.metric) if target in AUX_TARGETS else CONTEXT_READS


class Rejected(Exception):
    """Request rejected before any PLC write."""


class Uncertain(Exception):
    """Write or following state not confirmed; no automatic resend."""


def target_by_key(key: str) -> Target:
    for target in TARGETS:
        if target.key == key:
            return target
    raise ValueError("Unknown control target")


def canonical_value(target: Target, value: float) -> float:
    if target not in TARGETS or not math.isfinite(value) or not target.minimum <= value <= target.maximum:
        raise ValueError("Value outside owner-specified finite range")
    if target in AUX_TARGETS and value not in (0, 1):
        raise ValueError("Motor command accepts exactly 0 or 1")
    return float(struct.unpack(">f", struct.pack(">f", value))[0])


def read_job(reference: int, metrics: tuple[core.Metric, ...]) -> bytes:
    if not metrics or not all(m in ALLOWED_READS for m in metrics):
        raise ValueError("Read selector is not on whitelist")
    parameter = bytes((4, len(metrics))) + b"".join(m.selector() for m in metrics)
    pdu = struct.pack(">BBHHHH", 0x32, 1, 0, reference, len(parameter), 0) + parameter
    if len(pdu) > 240:
        raise ValueError("Read exceeds PDU limit")
    return core.tpkt(b"\2\xf0\x80" + pdu)


def write_job(reference: int, target: Target, value: float) -> bytes:
    value = canonical_value(target, value)
    parameter = b"\5\1" + target.metric.selector()
    if target in AUX_TARGETS:
        data = b"\xff\3\0\1" + (b"\xff" if value == 1 else b"\0")
    else:
        data = b"\xff\4\0\x20" + struct.pack(">f", value)
    pdu = struct.pack(">BBHHHH", 0x32, 1, 0, reference, len(parameter), len(data))
    return core.tpkt(b"\2\xf0\x80" + pdu + parameter + data)


def decode(metric: core.Metric, item: tuple[int, int, bytes]) -> float:
    code, transport, raw = item
    if metric.kind == "int16":
        if code != 255 or transport != 5 or len(raw) != 2:
            raise core.ProtocolError(f"Invalid INT16 for {metric.key}")
        return float(struct.unpack(">h", raw)[0])
    return core.decode_value(metric, item)


class ControlReader(core.S7Reader):
    def read_tags(self, metrics: tuple[core.Metric, ...]) -> dict[str, float]:
        if self.sock is None:
            raise core.ProtocolError("Not connected")
        ref = self.next_reference()
        packet = read_job(ref, metrics)
        if len(packet) - 7 > self.pdu_limit:
            raise core.ProtocolError("Read exceeds negotiated PDU limit")
        self.sock.sendall(packet)
        parameter, data = core.split_ack(core.receive_s7(self.sock), ref, 4)
        if parameter != bytes((4, len(metrics))):
            raise core.ProtocolError("Read item count mismatch")
        return {m.key: decode(m, item)
                for m, item in zip(metrics, core.parse_read_data(data, len(metrics)), strict=True)}

    def write_once(self, target: Target, value: float) -> None:
        if self.sock is None:
            raise Rejected("Not connected")
        ref = self.next_reference()
        packet = write_job(ref, target, value)
        if len(packet) - 7 > self.pdu_limit:
            raise Rejected("Write exceeds negotiated PDU limit")
        try:
            self.sock.sendall(packet)
            parameter, data = core.split_ack(core.receive_s7(self.sock), ref, 5)
            if parameter != b"\5\1" or data != b"\xff":
                raise core.ProtocolError("Write not positively acknowledged")
        except (OSError, core.ProtocolError, KeyboardInterrupt) as exc:
            raise Uncertain(f"Write acknowledgement unconfirmed: {exc}") from exc


def guard(values: dict[str, float], target: Target, value: float) -> None:
    needed = {m.key for m in context_for(target)}
    if not needed.issubset(values) or any(not math.isfinite(values[k]) for k in needed):
        raise Rejected("Missing/non-finite fresh context")
    if values["profile_auto"] != 0:
        raise Rejected("Panel automatic profile owns the setpoints; use manual profile mode")
    if target in AUX_TARGETS:
        if values[target.metric.key] not in (0, 1):
            raise Rejected("Invalid current motor command")
        return
    for known_target in SETPOINT_TARGETS:
        existing = values[known_target.metric.key]
        if not known_target.minimum <= existing <= known_target.maximum:
            raise Rejected(f"Current {known_target.key} SP outside owner range; inspect panel/scaling")
    if target.key == "air" and values["air_pressure_mode"] != 3:
        raise Rejected("Air pressure regulator must be in the mode reported as AutoCheck (3)")
    if target.key == "gas" and values["gas_pressure_mode"] != 3:
        raise Rejected("Gas pressure regulator must be in the mode reported as AutoCheck (3)")
    heat_requested = (values["gas_recipe_sp"] > 0 or values["gas_active_sp_mbar"] > 0
                      or values["burner_output_on"] != 0)
    if target.key in ("drum", "air") and value == 0 and heat_requested:
        raise Rejected("Set gas to zero and stop heating from the panel before zero drum/air")
    if target.key == "gas" and value > 0:
        if values["panel_run_command"] != 1:
            raise Rejected("Positive gas requires panel Roster:G enabled by the operator")
        if values["drum_recipe_sp"] <= 0 or values["drum_active_rpm"] <= 0:
            raise Rejected("Positive gas requires nonzero drum setpoints")
        if values["air_sp_pa"] <= 0 or values["air_pid_output_rpm"] <= 0:
            raise Rejected("Positive gas requires nonzero air SP and PID output")
    # The above are software operating checks on commands, not proof of motor
    # rotation, airflow, flame supervision or the machine's complete safety chain.


class ControlGateway:
    def __init__(self, reader: ControlReader | None = None):
        self.reader = reader if reader is not None else ControlReader()
        self.cache = core.Readings()
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.expected: dict[str, float] = {}
        self.values: dict[str, float] = {}
        self.inhibit: str | None = None
        self.last_write = {t.key: float("-inf") for t in TARGETS}

    def stop_commands(self) -> None:
        self.stopping.set()

    def close(self) -> None:
        self.stop_commands()
        with self.lock:
            self.reader.close()
            self.cache.invalidate("Control client stopped")

    def _read_group(self, metrics: tuple[core.Metric, ...]) -> dict[str, float]:
        values: dict[str, float] = {}
        for start in range(0, len(metrics), 8):
            values.update(self.reader.read_tags(metrics[start:start + 8]))
        return values

    def _observe(self, values: dict[str, float]) -> None:
        self.values.update(values)
        for target in SETPOINT_TARGETS:
            key = target.metric.key
            if key in values:
                if key in self.expected and values[key] != self.expected[key]:
                    self.inhibit = f"{target.key} SP changed externally; inspect panel and restart to re-arm"
                self.expected.setdefault(key, values[key])
        self.cache.update({k: v for k, v in values.items() if k in PUBLISHED_KEYS}, {})

    def refresh(self) -> dict[str, float]:
        with self.lock:
            if self.stopping.is_set():
                raise core.ProtocolError("Client stopped")
            try:
                if self.reader.sock is None:
                    self.reader.connect()
                values = self._read_group(ALL_READS)
                self._observe(values)
                return values
            except (OSError, core.ProtocolError) as exc:
                self.cache.invalidate(str(exc))
                if self.expected:
                    self.inhibit = "PLC read/connection error; commands disabled until inspected/restarted"
                self.reader.close()
                raise

    def set_target(self, target: Target, value: float) -> dict[str, object]:
        try:
            value = canonical_value(target, value)
        except ValueError as exc:
            raise Rejected(str(exc)) from exc
        entered = time.monotonic()
        if not self.lock.acquire(timeout=0.25):
            raise Rejected("Client busy; no command queued")
        try:
            if self.stopping.is_set():
                raise Rejected("Client stopping/stopped")
            if self.inhibit:
                raise Rejected(self.inhibit)
            if self.reader.sock is None:
                raise Rejected("Wait for fresh telemetry")
            before: dict[str, float] = {}
            try:
                before = self._read_group(context_for(target))
                self._observe(before)
            except (OSError, core.ProtocolError) as exc:
                self.inhibit = f"Preflight read failed: {exc}; restart after inspection"
                self.cache.invalidate(self.inhibit)
                self.reader.close()
                raise Rejected(self.inhibit) from exc
            if self.inhibit:
                raise Rejected(self.inhibit)
            guard(before, target, value)
            if self.stopping.is_set() or time.monotonic() - entered > 1.5:
                raise Rejected("Stopped/expired during preflight; no write sent")
            if before[target.metric.key] == value:
                return self.result("already_set", target, value, before, before)
            if (time.monotonic() - self.last_write[target.key] < 0.5
                    and not (value == 0 and (target.key == "gas" or target in AUX_TARGETS))):
                raise Rejected("Wait 0.5 seconds between changes of this setpoint")
            LOG.warning("WRITE-ONCE %s %.4f -> %.4f; context=%s", target.key,
                        before[target.metric.key], value, json.dumps(before))
            if self.stopping.is_set() or time.monotonic() - entered > 1.5:
                raise Rejected("Stopped/expired before write admission; no write sent")
            self.last_write[target.key] = time.monotonic()
            try:
                self.reader.write_once(target, value)
                after: dict[str, float] = {}
                for attempt in range(4):
                    if attempt:
                        time.sleep(0.15)
                    after = self._read_group(context_for(target))
                    if after[target.metric.key] == value:
                        self.expected[target.metric.key] = value
                        self._observe(after)
                        if self.inhibit:
                            raise Uncertain(self.inhibit)
                        # Stored setpoint is the verification target. A PID
                        # output, measured pressure or warmup ActSp can differ.
                        try:
                            guard(after, target, value)
                        except Rejected as exc:
                            raise Uncertain(f"Operating context changed during command: {exc}") from exc
                        result = self.result("verified", target, value, before, after)
                        LOG.warning("VERIFIED stored %s=%s active=%s measured=%s",
                                    target.key, value, result["active_value"], result["measured_value"])
                        return result
                raise Uncertain("Stored SP readback did not match requested value")
            except (OSError, core.ProtocolError, Uncertain, KeyboardInterrupt) as exc:
                self.inhibit = f"WRITE OUTCOME/STATE UNCONFIRMED: {exc}. No resend; inspect panel."
                self.cache.invalidate(self.inhibit)
                self.reader.close()
                LOG.error(self.inhibit)
                raise Uncertain(self.inhibit) from exc
        finally:
            self.lock.release()

    @staticmethod
    def result(status: str, target: Target, value: float, before: dict[str, float], after: dict[str, float]) -> dict[str, object]:
        active = after.get(target.active_key) if target.active_key else None
        return {"result": status, "target": target.key, "requested": value,
                "stored_value": after[target.metric.key], "active_value": active,
                "active_matches": ((active == 0 if value == 0 else abs(active - value) <= 0.01)
                                   if active is not None else None),
                "measured_value": after.get(target.measured_key) if target.measured_key else None,
                "before": before, "after": after}

    def register_data(self, start: int, count: int) -> bytes:
        if start < 20 and start + count <= 20:
            return self.cache.registers(start, count)
        # The target registers can also be read back from the fresh cache.
        if start < 100 or start + count > 112 or count < 1:
            raise ValueError("Unknown register range")
        now = time.monotonic()
        with self.cache.lock:
            data = bytearray()
            first = (start - 100) // 2
            last = (start + count - 1 - 100) // 2
            for target in TARGETS[first:last + 1]:
                entry = self.cache.values.get(target.metric.key)
                if entry is None or now - entry[1] > self.cache.stale_after:
                    raise core.ProtocolError("Target SP unavailable/stale")
                data.extend(struct.pack(">f", entry[0]))
            skip = ((start - 100) % 2) * 2
            return bytes(data[skip:skip + count * 2])


def modbus_pdu(pdu: bytes, unit: int, gateway: ControlGateway) -> bytes:
    function = pdu[0] if pdu else 0
    if function in (3, 4):
        if unit != 1 or len(pdu) != 5:
            return bytes((function | 128, 3))
        start, count = struct.unpack(">HH", pdu[1:])
        if not 1 <= count <= 125:
            return bytes((function | 128, 3))
        try:
            data = gateway.register_data(start, count)
        except ValueError:
            return bytes((function | 128, 2))
        except core.ProtocolError:
            return bytes((function | 128, 4))
        return bytes((function, len(data))) + data
    if function != 16:
        return bytes((function | 128, 1))
    if unit != 1 or len(pdu) != 10:
        return b"\x90\3"
    start, count, byte_count = struct.unpack(">HHB", pdu[1:6])
    target = next((t for t in TARGETS if t.register == start), None)
    if target is None:
        return b"\x90\2"
    if count != 2 or byte_count != 4:
        return b"\x90\3"
    value = struct.unpack(">f", pdu[6:])[0]
    try:
        canonical_value(target, value)
    except ValueError:
        return b"\x90\3"
    try:
        gateway.set_target(target, value)
    except Rejected as exc:
        LOG.warning("REJECTED no write: %s", exc)
        return b"\x90\6"
    except Uncertain as exc:
        LOG.error("Command not verified: %s", exc)
        return b"\x90\4"
    return struct.pack(">BHH", 16, start, 2)


class Handler(socketserver.BaseRequestHandler):
    @override
    def handle(self) -> None:
        self.request.settimeout(10)
        try:
            while True:
                header = core.read_exact(self.request, 7)
                transaction, protocol, length, unit = struct.unpack(">HHHB", header)
                if protocol or not 2 <= length <= 254:
                    return
                server = cast('Server', self.server)
                reply = modbus_pdu(core.read_exact(self.request, length - 1), unit, server.gateway)
                self.request.sendall(struct.pack(">HHHB", transaction, 0, len(reply) + 1, unit) + reply)
        except (OSError, core.ProtocolError):
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, gateway: ControlGateway, port: int = core.MODBUS_PORT):
        self.gateway = gateway
        super().__init__((core.MODBUS_HOST, port), Handler)


def poll(gateway: ControlGateway, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            gateway.refresh()
            stop.wait(1)
        except (OSError, core.ProtocolError) as exc:
            LOG.error("No fresh PLC data: %s", exc)
            stop.wait(5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect", action="store_true")
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--set", nargs=2, metavar=("TARGET", "VALUE"))
    mode.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        import unittest
        LOG.setLevel(logging.CRITICAL + 1)
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent / "tests"), pattern="test_*.py")
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    target: Target | None = None
    value = 0.0
    if args.set:
        try:
            target = target_by_key(args.set[0])
            value = canonical_value(target, float(args.set[1]))
        except ValueError as exc:
            parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log_path = Path(__file__).resolve().parent / "trobrat-control.log"
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.warning("DIRECT SP CONTROL: drum0..65,air0..300,gas0..20. Positive gas can ignite. Log: %s", log_path)
    gateway = ControlGateway()
    if args.inspect or args.set:
        try:
            values = gateway.refresh()
            if args.inspect:
                readiness = {}
                for t in SETPOINT_TARGETS:
                    try:
                        guard(values, t, values[t.metric.key])
                        readiness[t.key] = "ready for current SP; positive-gas checks run per command"
                    except Rejected as exc:
                        readiness[t.key] = str(exc)
                try:
                    guard(values, target_by_key("gas"), 1.5)
                    positive_gas = "software conditions met; no write sent"
                except Rejected as exc:
                    positive_gas = str(exc)
                result = {"values": values, "readiness": readiness,
                          "positive_gas_readiness": positive_gas, "write_sent": False}
                LOG.info("INSPECT %s", json.dumps(result))
                print(json.dumps(result, indent=2))
                return 0
            assert target is not None
            print(json.dumps(gateway.set_target(target, value), indent=2))
            return 0
        except (OSError, core.ProtocolError, Rejected, Uncertain) as exc:
            LOG.error("Stopped: %s", exc)
            return 1
        finally:
            gateway.close()
    try:
        server = Server(gateway)
    except OSError as exc:
        LOG.error("Port15020 unavailable; stop the old reader/control window first: %s", exc)
        return 1
    stop = threading.Event()
    worker = threading.Thread(target=poll, args=(gateway, stop), daemon=True)
    worker.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    LOG.warning("Local control 127.0.0.1:15020: FC16unit1reg100drum/102air/104gas/106mixer/108cooler/110destoner. No writes on startup.")
    try:
        while not stop.wait(5):
            LOG.info("State inhibit=%s readings=%s", gateway.inhibit, json.dumps(gateway.cache.snapshot()))
    except KeyboardInterrupt:
        LOG.warning("Stopping client. Last PLC SP remains; use panel/manual controls for equipment shutdown.")
    finally:
        gateway.stop_commands()
        stop.set()
        server.shutdown()
        server.server_close()
        worker.join(3)
        gateway.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
