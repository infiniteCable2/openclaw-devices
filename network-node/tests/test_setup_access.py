import importlib.util
import csv
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("setup_access", Path(__file__).parents[1] / "tools/setup_access.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
REPLY = {"type": "netnode.setup-access", "version": 1, "ssid": "OpenClaw-Setup-ABCDEF",
         "password": "0123456789abcdef01234567", "username": "admin", "url": "http://192.168.4.1"}
REPLY["sha256"] = hashlib.sha256(f"{REPLY['ssid']}\n{REPLY['password']}".encode("ascii")).hexdigest()


class FakePort:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.sent = []
        self.closed = False
        self.now = 0.0

    def open(self):
        assert self.dtr is False and self.rts is False
        assert self.port == "test-port"

    def read(self, count):
        assert count == 256
        self.now += 0.2
        return next(self.chunks, b"")

    def write(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


class SetupAccessTest(unittest.TestCase):
    def test_schema_and_secret_scope(self):
        parsed = tool.parse_access(json.dumps({**REPLY, "unexpectedSecret": "not-exported"}))
        self.assertEqual(set(parsed), {"ssid", "password", "username", "url"})
        for changes in ({"version": True}, {"version": 2}, {"password": "bad"}, {"ssid": "other"},
                        {"url": "https://example.org"}, {"username": "other"}, {"type": "other"},
                        {"password": "1123456789abcdef01234567"}, {"sha256": "invalid"}):
            self.assertIsNone(tool.parse_access(json.dumps({**REPLY, **changes})))
        for invalid in (b"boot log", b"\xff", b"[]", b"x" * 513):
            self.assertIsNone(tool.parse_access(invalid))

    def query(self, port):
        with patch.dict(sys.modules, {"serial": types.SimpleNamespace(Serial=lambda **_kwargs: port)}):
            with patch.object(tool.time, "monotonic", side_effect=lambda: port.now):
                return tool.query_access("test-port", timeout=3)

    def test_boot_noise_fragmentation_and_close(self):
        reply = json.dumps(REPLY).encode() + b"\n"
        port = FakePort([b"booting\n", reply[:20], reply[20:200], reply[200:]])
        self.assertEqual(self.query(port)["password"], REPLY["password"])
        self.assertTrue(port.closed)
        self.assertEqual(port.sent, [tool.REQUEST])

    def test_overlong_line_is_discarded_until_newline(self):
        reply = json.dumps(REPLY).encode() + b"\n"
        port = FakePort([b"x" * 256, b"x" * 256, b"x", reply[:200], reply[200:], reply[:200], reply[200:]])
        self.assertEqual(self.query(port)["ssid"], REPLY["ssid"])
        self.assertTrue(port.closed)

    def test_timeout_closes_and_only_sends_read_request(self):
        port = FakePort([b"old firmware\n"])
        with self.assertRaises(TimeoutError):
            self.query(port)
        self.assertTrue(port.closed)
        self.assertGreater(len(port.sent), 1)
        self.assertEqual(set(port.sent), {tool.REQUEST})

    def test_write_failure_still_closes_port(self):
        port = FakePort([])
        port.write = unittest.mock.Mock(side_effect=OSError("disconnected"))
        with self.assertRaises(OSError):
            self.query(port)
        self.assertTrue(port.closed)


class PartitionCompatibilityTest(unittest.TestCase):
    def test_upgrade_keeps_original_state_and_application_ranges(self):
        # The old layouts are an upgrade compatibility contract, not a snapshot.
        root = Path(__file__).parents[1]
        for profile, app_size in (("esp32-4mb", 0x3E0000), ("esp32s3-16mb", 0x400000)):
            with self.subTest(profile=profile):
                text = (root / "boards" / profile / "partitions.csv").read_text()
                rows = list(csv.reader(line for line in text.splitlines() if not line.startswith("#")))
                entries = {row[0].strip(): (row[1].strip(), row[2].strip(), int(row[3], 0), int(row[4], 0))
                           for row in rows if row}
                self.assertEqual(entries["nvs"], ("data", "nvs", 0x9000, 0x10000))
                self.assertEqual(entries["phy_init"], ("data", "phy", 0x19000, 0x1000))
                self.assertEqual(entries["factory"], ("app", "factory", 0x20000, app_size))
                self.assertEqual(entries["provision"][:2], ("data", "nvs"))
                start, size = entries["provision"][2:]
                self.assertGreaterEqual(start, 0x1A000)
                self.assertEqual(start % 4096, 0)
                self.assertGreaterEqual(size, 3 * 4096)
                self.assertLessEqual(start + size, 0x20000)


if __name__ == "__main__":
    unittest.main()
