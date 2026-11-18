import json
from pathlib import Path
import struct
import unittest
from artisanlib.trobrat import control as c
from test_control import FakeReader


class MotorTests(unittest.TestCase):
    def test_recorded_mixer_cooler_write_packets_match(self):
        records = json.loads((Path(__file__).parent / "observed-motor-writes.json").read_text())
        self.assertEqual(len(records), 4)
        for record in records:
            target = next(t for t in c.AUX_TARGETS if t.metric.tag == record["tag"])
            self.assertEqual(c.write_job(record["reference"], target, record["value"]).hex(), record["request_hex"])

    def test_each_motor_on_off_only_and_readback(self):
        for target in c.AUX_TARGETS:
            reader = FakeReader()
            gateway = c.ControlGateway(reader)
            gateway.refresh()
            result = gateway.set_target(target, 1)
            self.assertEqual(result["stored_value"], 1)
            result = gateway.set_target(target, 0)
            self.assertEqual(result["stored_value"], 0)
            self.assertEqual(reader.writes, [(target.key, 1), (target.key, 0)])
            for invalid in (0.1, 0.5, -1, 2):
                with self.assertRaises(ValueError):
                    c.write_job(1, target, invalid)

    def test_motor_modbus_float_commands_and_base_registers(self):
        reader = FakeReader()
        gateway = c.ControlGateway(reader)
        gateway.refresh()
        self.assertEqual(struct.unpack(">3f", gateway.register_data(100, 6)), (55, 120, 0))
        for target in c.AUX_TARGETS:
            pdu = struct.pack(">BHHBf", 16, target.register, 2, 4, 1)
            self.assertEqual(c.modbus_pdu(pdu, 1, gateway), struct.pack(">BHH", 16, target.register, 2))
            self.assertEqual(struct.unpack(">f", gateway.register_data(target.register, 2))[0], 1)

    def test_motor_unknown_read_sends_no_write_and_does_not_change_primary_read_list(self):
        reader = FakeReader()
        gateway = c.ControlGateway(reader)
        gateway.refresh()
        reader.fail_read = True
        with self.assertRaises(c.Rejected):
            gateway.set_target(c.AUX_TARGETS[2], 1)
        self.assertEqual(reader.writes, [])
        self.assertTrue(all(t.metric not in c.ALL_READS for t in c.AUX_TARGETS))

    def test_panel_motor_change_does_not_inhibit_primary_sp(self):
        reader = FakeReader()
        gateway = c.ControlGateway(reader)
        gateway.refresh()
        gateway._observe({"mixer_manual_command": 1})
        self.assertIsNone(gateway.inhibit)


if __name__ == "__main__":
    unittest.main()
