"""Recorded payloads, fake PLC state and loopback-only Modbus tests."""
import ast
import json
from pathlib import Path
from typing import override
import socket
import struct
import threading
import unittest
from unittest import mock

from artisanlib.trobrat import control as c


class FakeReader:
    def __init__(self):
        self.sock = None
        self.values = {m.key: 0.0 for m in c.ALLOWED_READS}
        self.values.update(drum_recipe_sp=55, drum_active_rpm=55, air_sp_pa=120,
                           air_pid_output_rpm=900, gas_pressure_mode=3,
                           air_pressure_mode=3, panel_run_command=1)
        self.writes = []
        self.fail_read = False
        self.lost_ack = False
        self.no_effect = False
        self.active_differs = False
        self.change_other_after_write = False

    def connect(self):
        self.sock = object()

    def close(self):
        self.sock = None

    def read_tags(self, metrics):
        if self.fail_read:
            raise c.core.ProtocolError("Fake read failure")
        return {m.key: self.values[m.key] for m in metrics}

    def write_once(self, target, value):
        self.writes.append((target.key, value))
        if self.lost_ack:
            raise c.Uncertain("Fake lost acknowledgement")
        if not self.no_effect:
            self.values[target.metric.key] = value
            if target.active_key and not self.active_differs:
                self.values[target.active_key] = value
            if self.change_other_after_write:
                self.values["air_sp_pa"] = 180


class ScriptedSocket:
    def __init__(self, response):
        self.response = bytearray(response)
        self.sent = []

    def sendall(self, payload):
        self.sent.append(payload)

    def recv(self, count):
        if not self.response:
            raise TimeoutError("Fake timeout")
        count = min(2, count)
        result = bytes(self.response[:count])
        del self.response[:count]
        return result


class ProtocolTests(unittest.TestCase):
    def test_all_seven_recorded_write_requests_match_exactly(self):
        fixtures = json.loads((Path(__file__).parent / "observed-writes.json").read_text())
        self.assertEqual(len(fixtures), 7)
        for fixture in fixtures:
            target = next(t for t in c.TARGETS if t.metric.tag == fixture["tag"])
            self.assertEqual(c.write_job(fixture["reference"], target, fixture["value"]).hex(), fixture["request_hex"])
            parameter, data = c.core.split_ack(bytes.fromhex(fixture["response_hex"])[7:], fixture["reference"], 5)
            self.assertEqual((parameter, data), (b"\5\1", b"\xff"))

    def test_pressure_modes_decode_recorded_int16(self):
        fixtures = json.loads((Path(__file__).parent / "recorded-modes.json").read_text())
        for fixture in fixtures:
            metric = next(m for m in (c.AIR_MODE, c.GAS_MODE) if m.tag == fixture["tag"])
            parameter, data = c.core.split_ack(bytes.fromhex(fixture["response_hex"])[7:], fixture["reference"], 4)
            item = c.core.parse_read_data(data, parameter[1])[fixture["item_index"]]
            self.assertEqual(c.decode(metric, item), 3)

    def test_limits_and_finiteness_all_targets(self):
        for target in c.SETPOINT_TARGETS:
            for value in (target.minimum, target.maximum):
                self.assertIsInstance(c.write_job(1, target, value), bytes)
            for value in (-0.1, target.maximum + 0.1, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    c.write_job(1, target, value)
        unknown = c.Target("gas", c.GAS_SP, 104, 0, 2000, None, None)
        with self.assertRaises(ValueError):
            c.write_job(1, unknown, 100)
        for start in range(0, len(c.ALL_READS), 8):
            self.assertLessEqual(len(c.read_job(1, c.ALL_READS[start:start + 8])) - 7, 240)

    def test_real_write_method_sends_once_on_ack_loss(self):
        reader = c.ControlReader()
        scripted_socket = ScriptedSocket(b"")
        reader.sock = scripted_socket  # type: ignore[assignment]
        with self.assertRaises(c.Uncertain):
            reader.write_once(c.target_by_key("gas"), 1.5)
        self.assertEqual(len(scripted_socket.sent), 1)

    def test_generated_palette_commands_and_gas_tenths(self):
        palette = ast.literal_eval((Path(__file__).parent / "Trobrat-Direct.apal").read_text())["0"]
        self.assertEqual(palette[19][:3], [0, 0, 0])
        self.assertEqual(palette[20][:3], [65, 300, 200])
        self.assertEqual(palette[13][:3], [1, 1, 0.1])
        self.assertEqual(palette[11][:3], ["writeWord(1,100,{})", "writeWord(1,102,{})", "writeWord(1,104,{})"])
        self.assertIn("writeWord(1,104,1.5)", palette[4])
        self.assertTrue(all("{}" not in command for command in palette[4]))
        self.assertEqual(15 * palette[13][2], 1.5)


class GatewayTests(unittest.TestCase):
    @override
    def setUp(self):
        self.reader = FakeReader()
        self.gateway = c.ControlGateway(self.reader)
        self.gateway.refresh()

    def test_three_targets_write_once_verify_stored_and_keep_distinct_measurements(self):
        for key, value in (("drum", 50), ("air", 100), ("gas", 1.5)):
            result = self.gateway.set_target(c.target_by_key(key), value)
            self.assertEqual(result["result"], "verified")
            self.assertEqual(result["stored_value"], value)
        self.assertEqual(self.reader.writes, [("drum", 50), ("air", 100), ("gas", 1.5)])

    def test_active_and_measured_difference_is_not_false_readback_failure(self):
        self.reader.active_differs = True
        result = self.gateway.set_target(c.target_by_key("gas"), 5)
        self.assertEqual(result["result"], "verified")
        self.assertEqual(result["stored_value"], 5)
        self.assertEqual(result["active_value"], 0)
        self.assertFalse(result["active_matches"])
        self.assertEqual(result["measured_value"], 0)

    def test_profile_pressure_mode_and_positive_gas_guards(self):
        cases = [("profile_auto", 1, "drum", 50), ("gas_pressure_mode", 0, "gas", 1.5),
                 ("air_pressure_mode", 0, "air", 100), ("panel_run_command", 0, "gas", 1.5),
                 ("drum_active_rpm", 0, "gas", 1.5), ("air_pid_output_rpm", 0, "gas", 1.5)]
        for field, value, target, requested in cases:
            reader = FakeReader()
            reader.values[field] = value
            gateway = c.ControlGateway(reader)
            gateway.refresh()
            with self.subTest(field=field), self.assertRaises(c.Rejected):
                gateway.set_target(c.target_by_key(target), requested)
            self.assertEqual(reader.writes, [])

    def test_zero_drum_air_blocked_while_heat_requested_gas_zero_remains_normal_command(self):
        for key in ("drum", "air"):
            reader = FakeReader()
            reader.values["gas_recipe_sp"] = 1.5
            gateway = c.ControlGateway(reader)
            gateway.refresh()
            with self.assertRaises(c.Rejected):
                gateway.set_target(c.target_by_key(key), 0)
            result = gateway.set_target(c.target_by_key("gas"), 0)
            self.assertEqual(result["result"], "verified")
            self.assertEqual(reader.writes, [("gas", 0)])

    def test_owner_maxima_accepted(self):
        for target in c.SETPOINT_TARGETS:
            reader = FakeReader()
            gateway = c.ControlGateway(reader)
            gateway.refresh()
            result = gateway.set_target(target, target.maximum)
            self.assertEqual(result["stored_value"], target.maximum)

    def test_manual_roast_flag_does_not_disable_control_without_profile_replay(self):
        self.reader.values["roast_on"] = 1
        result = self.gateway.set_target(c.target_by_key("air"), 100)
        self.assertEqual(result["result"], "verified")

    def test_out_of_range_existing_sp_stops_write(self):
        self.reader.values["gas_recipe_sp"] = 21
        gateway = c.ControlGateway(self.reader)
        gateway.refresh()
        with self.assertRaises(c.Rejected):
            gateway.set_target(c.target_by_key("drum"), 50)
        self.assertEqual(self.reader.writes, [])

    def test_panel_change_latches_and_does_not_fight_panel(self):
        self.reader.values["air_sp_pa"] = 150
        with self.assertRaises(c.Rejected):
            self.gateway.set_target(c.target_by_key("gas"), 1.5)
        self.assertEqual(self.reader.writes, [])
        self.assertIsNotNone(self.gateway.inhibit)

    def test_other_sp_change_during_write_is_reported_and_latched(self):
        self.reader.change_other_after_write = True
        with self.assertRaises(c.Uncertain):
            self.gateway.set_target(c.target_by_key("gas"), 1.5)
        self.assertEqual(self.reader.writes, [("gas", 1.5)])
        self.assertIsNotNone(self.gateway.inhibit)

    def test_lost_ack_latches_no_repeat_even_after_reconnect(self):
        self.reader.lost_ack = True
        with self.assertRaises(c.Uncertain):
            self.gateway.set_target(c.target_by_key("gas"), 1.5)
        self.reader.lost_ack = False
        self.gateway.refresh()
        with self.assertRaises(c.Rejected):
            self.gateway.set_target(c.target_by_key("gas"), 1.5)
        self.assertEqual(self.reader.writes, [("gas", 1.5)])

    def test_ack_without_stored_readback_latches(self):
        self.reader.no_effect = True
        with mock.patch.object(c.time, "sleep"), self.assertRaises(c.Uncertain):
            self.gateway.set_target(c.target_by_key("air"), 100)
        self.assertEqual(self.reader.writes, [("air", 100)])

    def test_duplicate_and_rate_limit_do_not_resend(self):
        target = c.target_by_key("drum")
        self.assertEqual(self.gateway.set_target(target, 55)["result"], "already_set")
        self.gateway.set_target(target, 50)
        self.assertEqual(self.gateway.set_target(target, 50)["result"], "already_set")
        with self.assertRaises(c.Rejected):
            self.gateway.set_target(target, 55)
        self.assertEqual(self.reader.writes, [("drum", 50)])

    def test_zero_gas_not_delayed_by_change_rate_limit(self):
        target = c.target_by_key("gas")
        self.gateway.set_target(target, 1.5)
        result = self.gateway.set_target(target, 0)
        self.assertEqual(result["stored_value"], 0)
        self.assertEqual(self.reader.writes, [("gas", 1.5), ("gas", 0)])

    def test_stop_before_and_during_prewrite_log(self):
        with mock.patch.object(c.LOG, "warning", side_effect=lambda *a, **kw: self.gateway.stop_commands()), self.assertRaises(c.Rejected):
            self.gateway.set_target(c.target_by_key("gas"), 1.5)
        self.assertEqual(self.reader.writes, [])
        with self.assertRaises(c.Rejected):
            self.gateway.set_target(c.target_by_key("air"), 100)

    def test_slow_preflight_expires_without_write(self):
        clock = [10.0]
        original = self.reader.read_tags

        def slow_read(metrics):
            clock[0] += 1
            return original(metrics)

        self.reader.read_tags = slow_read  # type: ignore[method-assign]
        with mock.patch.object(c.time, "monotonic", side_effect=lambda: clock[0]), self.assertRaises(c.Rejected):
            self.gateway.set_target(c.target_by_key("drum"), 50)
        self.assertEqual(self.reader.writes, [])

    def test_zero_gas_is_exact_not_a_positive_tolerance_noop(self):
        self.reader.values["gas_recipe_sp"] = c.canonical_value(c.target_by_key("gas"), 0.00005)
        gateway = c.ControlGateway(self.reader)
        gateway.refresh()
        result = gateway.set_target(c.target_by_key("gas"), 0)
        self.assertEqual(result["stored_value"], 0)
        self.assertEqual(self.reader.writes, [("gas", 0)])

    def test_tiny_external_positive_gas_change_from_zero_is_detected(self):
        self.reader.values["gas_recipe_sp"] = 0.00005
        with self.assertRaises(c.Rejected):
            self.gateway.set_target(c.target_by_key("air"), 100)
        self.assertIsNotNone(self.gateway.inhibit)
        self.assertEqual(self.reader.writes, [])

    def test_no_queue_for_busy_client(self):
        held, release = threading.Event(), threading.Event()

        def hold():
            with self.gateway.lock:
                held.set()
                release.wait(2)

        worker = threading.Thread(target=hold)
        worker.start()
        self.assertTrue(held.wait(2))
        try:
            with self.assertRaises(c.Rejected):
                self.gateway.set_target(c.target_by_key("gas"), 1.5)
            self.assertEqual(self.reader.writes, [])
        finally:
            release.set()
            worker.join(3)

    def test_target_registers_fresh_and_stale(self):
        self.assertEqual(struct.unpack(">3f", self.gateway.register_data(100, 6)), (55, 120, 0))
        self.gateway.set_target(c.target_by_key("gas"), 1.5)
        self.assertEqual(struct.unpack(">f", self.gateway.register_data(104, 2))[0], 1.5)
        self.gateway.cache.invalidate("disconnect")
        with self.assertRaises(c.core.ProtocolError):
            self.gateway.register_data(104, 2)


class ModbusTests(unittest.TestCase):
    @override
    def setUp(self):
        self.reader = FakeReader()
        self.gateway = c.ControlGateway(self.reader)
        self.gateway.refresh()

    @staticmethod
    def request(address, value):
        return struct.pack(">BHHBf", 16, address, 2, 4, value)

    def test_whitelist_full_floats_only(self):
        for address in (0, 2, 8, 12, 99, 101, 103, 105, 107, 109, 111, 112):
            self.assertEqual(c.modbus_pdu(self.request(address, 1), 1, self.gateway), b"\x90\2")
        for function in (5, 6, 15, 22, 23):
            self.assertEqual(c.modbus_pdu(bytes((function,)) + b"\0" * 12, 1, self.gateway), bytes((function | 128, 1)))
        self.assertEqual(c.modbus_pdu(self.request(104, 21), 1, self.gateway), b"\x90\3")
        self.assertEqual(c.modbus_pdu(self.request(104, float("nan")), 1, self.gateway), b"\x90\3")
        self.assertEqual(c.modbus_pdu(self.request(104, 1.5), 0, self.gateway), b"\x90\3")
        self.assertEqual(self.reader.writes, [])

    def test_read_telemetry_and_target_maps(self):
        self.assertEqual(c.modbus_pdu(bytes.fromhex("0300040002"), 1, self.gateway), b"\3\4" + struct.pack(">f", 55))
        self.assertEqual(c.modbus_pdu(bytes.fromhex("0300640006"), 1, self.gateway), b"\3\x0c" + struct.pack(">3f", 55, 120, 0))
        self.assertEqual(c.modbus_pdu(bytes.fromhex("0300140002"), 1, self.gateway), b"\x83\2")

    def test_loopback_gas_command_calls_fake_reader_and_returns_verified_ack(self):
        server = c.Server(self.gateway, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as sock:
                pdu = self.request(104, 1.5)
                sock.sendall(struct.pack(">HHHB", 11, 0, len(pdu) + 1, 1) + pdu)
                tx, protocol, length, unit = struct.unpack(">HHHB", c.core.read_exact(sock, 7))
                self.assertEqual((tx, protocol, unit), (11, 0, 1))
                self.assertEqual(c.core.read_exact(sock, length - 1), bytes.fromhex("1000680002"))
                self.assertEqual(self.reader.writes, [("gas", 1.5)])
        finally:
            self.gateway.stop_commands()
            server.shutdown()
            server.server_close()
            worker.join(3)
            self.gateway.close()


if __name__ == "__main__":
    unittest.main()
