"""Offline historical-payload tests and loopback-only protocol tests."""
import json
from pathlib import Path
import socket
import struct
import threading
from typing import override
import unittest
from unittest import mock

from artisanlib.trobrat import metrics as bm

FIXTURE = json.loads((Path(__file__).parent / "recorded_payloads.json").read_text())


class RecordedProtocolTests(unittest.TestCase):
    def test_original_response_bytes_and_selectors(self):
        found = set()
        for transaction in FIXTURE["transactions"]:
            request = bytes.fromhex(transaction["request_hex"])
            response = bytes.fromhex(transaction["response_hex"])
            ref = int.from_bytes(request[11:13], "big")
            parameter, data = bm.split_ack(response[7:], ref, 4)
            items = bm.parse_read_data(data, parameter[1])
            self.assertEqual(len(items), len(transaction["tags"]))
            for tag, expected, item in zip(transaction["tags"], transaction["expected_values"], items, strict=True):
                metric = next((m for m in bm.METRICS if m.tag == tag), None)
                if metric:
                    self.assertIn(metric.selector(), request)
                    self.assertEqual(bm.decode_value(metric, item), expected)
                    found.add(metric.key)
        self.assertEqual(found, {m.key for m in bm.METRICS})

    def test_only_read_and_setup_can_be_generated(self):
        self.assertEqual(bm.COTP_CONNECT.hex(), FIXTURE["cotp_connect_hex"])
        setup = bm.make_job(0xF0, 1)
        read = bm.make_job(4, 2, bm.METRICS)
        self.assertEqual(setup[17:], bm.SETUP_PARAMETER)
        self.assertEqual(read[17:19], bytes((4, 10)))
        self.assertLessEqual(len(read) - 7, 240)
        for function in range(256):
            if function not in (4, 0xF0):
                with self.assertRaises(ValueError):
                    bm.make_job(function, 1, bm.METRICS)

    def test_malformed_ack_and_data_rejected(self):
        original = bytes.fromhex(FIXTURE["transactions"][0]["response_hex"])[7:]
        ref = int.from_bytes(original[4:6], "big")
        with self.assertRaises(bm.ProtocolError):
            bm.split_ack(original, ref + 1, 4)
        with self.assertRaises(bm.ProtocolError):
            bm.split_ack(original + b"\0", ref, 4)
        bad = bytearray(original)
        bad[10] = 0x81
        with self.assertRaises(bm.ProtocolError):
            bm.split_ack(bytes(bad), ref, 4)
        with self.assertRaises(bm.ProtocolError):
            bm.parse_read_data(bytes.fromhex("ff0700040000"), 1)
        with self.assertRaises(bm.ProtocolError):
            bm.parse_read_data(bytes.fromhex("ff03000101ff0700043fc00000"), 2)

    def test_nonfinite_and_item_error_rejected(self):
        for raw in (bytes.fromhex("7fc00000"), bytes.fromhex("7f800000")):
            with self.assertRaises(bm.ProtocolError):
                bm.decode_value(bm.METRICS[0], (255, 7, raw))
        with self.assertRaises(bm.ProtocolError):
            bm.decode_value(bm.METRICS[0], (5, 0, b""))
        with self.assertRaises(bm.ProtocolError):
            bm.decode_value(bm.METRICS[0], (255, 4, bytes.fromhex("3fc00000")))


class ModbusTests(unittest.TestCase):
    @override
    def setUp(self):
        self.cache = bm.Readings()
        self.cache.update({m.key: 1.5 + i for i, m in enumerate(bm.METRICS)}, {})

    def test_register_order_range_and_unit(self):
        reply = bm.modbus_pdu(bytes.fromhex("0300000008"), 1, self.cache)
        self.assertEqual(reply[:2], b"\3\x10")
        self.assertEqual(struct.unpack(">4f", reply[2:]), (1.5, 2.5, 3.5, 4.5))
        self.assertEqual(self.cache.registers(1, 2), bytes.fromhex("00004020"))
        self.assertEqual(bm.modbus_pdu(bytes.fromhex("0300140002"), 1, self.cache), b"\x83\x02")
        self.assertEqual(bm.modbus_pdu(bytes.fromhex("0300000000"), 1, self.cache), b"\x83\x03")
        self.assertEqual(bm.modbus_pdu(bytes.fromhex("0300000002"), 0, self.cache), b"\x83\x03")

    def test_all_write_functions_rejected_without_changing_cache(self):
        previous = self.cache.registers(0, 20)
        for function in (5, 6, 15, 16, 22, 23):
            reply = bm.modbus_pdu(bytes((function,)) + b"\0" * 12, 1, self.cache)
            self.assertEqual(reply, bytes((function | 128, 1)))
        self.assertEqual(previous, self.cache.registers(0, 20))

    def test_stale_item_errors_and_disconnect_never_return_old_values(self):
        cache = bm.Readings()
        with mock.patch.object(bm.time, "monotonic", return_value=10):
            cache.update({"gas_mbar": 1.5}, {})
        with mock.patch.object(bm.time, "monotonic", return_value=14.01):
            self.assertEqual(bm.modbus_pdu(bytes.fromhex("0300000002"), 1, cache), b"\x83\x04")
            self.assertIsNone(cache.snapshot()["gas_mbar"]["value"])
        self.cache.update({}, {"gas_mbar": "PLC error"})
        self.assertEqual(bm.modbus_pdu(bytes.fromhex("0300000002"), 1, self.cache), b"\x83\x04")
        self.assertEqual(bm.modbus_pdu(bytes.fromhex("0300020002"), 1, self.cache)[:2], b"\3\4")
        self.cache.invalidate("Disconnected")
        self.assertEqual(bm.modbus_pdu(bytes.fromhex("0300020002"), 1, self.cache), b"\x83\x04")

    def test_real_modbus_tcp_loopback_reads_and_rejects_write(self):
        server = bm.ModbusServer(self.cache, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as sock:
                for ref, pdu, expected in ((17, bytes.fromhex("0300000002"), b"\3\4" + struct.pack(">f", 1.5)),
                                           (18, bytes.fromhex("0600000042"), b"\x86\1")):
                    message = struct.pack(">HHHB", ref, 0, len(pdu) + 1, 1) + pdu
                    sock.sendall(message[:3])
                    sock.sendall(message[3:])
                    header = bm.read_exact(sock, 7)
                    tx, protocol, length, unit = struct.unpack(">HHHB", header)
                    self.assertEqual((tx, protocol, unit), (ref, 0, 1))
                    self.assertEqual(bm.read_exact(sock, length - 1), expected)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


class S7LoopbackTests(unittest.TestCase):
    def test_full_connection_and_read_against_local_fixture_server(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)
        address = listener.getsockname()
        received, errors = [], []

        def respond():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(3)
                    cr = bm.receive_tpkt(peer)
                    received.append(bm.tpkt(cr))
                    self.assertEqual(received[-1], bm.COTP_CONNECT)
                    peer.sendall(bytes.fromhex(FIXTURE["cotp_confirm_hex"]))
                    for function in (0xF0, 4):
                        request = bm.receive_s7(peer)
                        received.append(request)
                        ref = int.from_bytes(request[4:6], "big")
                        self.assertEqual(request[10], function)
                        self.assertEqual(request[8:10], b"\0\0")  # no write data
                        if function == 0xF0:
                            parameter, data = bm.SETUP_PARAMETER, b""
                        else:
                            self.assertEqual(request[10:], bytes((4, len(bm.METRICS))) +
                                             b"".join(m.selector() for m in bm.METRICS))
                            parameter = bytes((4, len(bm.METRICS)))
                            data = bytearray()
                            for i, metric in enumerate(bm.METRICS):
                                item = FIXTURE["mock_items"][metric.tag]
                                raw = bytes.fromhex(item["hex"])
                                transport = item["transport"]
                                length = len(raw) * 8 if transport in (3, 4, 5) else len(raw)
                                data.extend(struct.pack(">BBH", 255, transport, length) + raw)
                                if len(raw) % 2 and i < len(bm.METRICS) - 1:
                                    data.extend(b"\0")
                            data = bytes(data)
                        ack = struct.pack(">BBHHHHBB", 0x32, 3, 0, ref,
                                          len(parameter), len(data), 0, 0) + parameter + data
                        packet = bm.tpkt(b"\2\xf0\x80" + ack)
                        peer.sendall(packet[:2])
                        peer.sendall(packet[2:8])
                        peer.sendall(packet[8:])
            except Exception as exc:
                errors.append(exc)
            finally:
                listener.close()

        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        original_connect = socket.create_connection

        def local_connect(target, timeout):
            self.assertEqual(target, (bm.PLC_HOST, 102))
            return original_connect(address, timeout)

        reader = bm.S7Reader()
        try:
            with mock.patch.object(bm.socket, "create_connection", side_effect=local_connect):
                reader.connect()
                values, item_errors = reader.read()
                self.assertFalse(item_errors)
                self.assertEqual(len(values), 10)
                for metric in bm.METRICS:
                    self.assertEqual(values[metric.key], FIXTURE["mock_items"][metric.tag]["value"])
        finally:
            reader.close()
            thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors, errors)
        self.assertEqual(len(received), 3)  # connection, setup, read; no other command


if __name__ == "__main__":
    unittest.main()
