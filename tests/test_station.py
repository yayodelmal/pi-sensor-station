import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from PIL import Image
from pi_sensor_station.api import API
from pi_sensor_station.display import rgb565
from pi_sensor_station.sensors import DS18B20, crc8, decode_ds18b20, decode_sht31


class SensorTests(unittest.TestCase):
    def test_sht31_crc_and_conversion(self):
        self.assertEqual(crc8(bytes.fromhex("beef")), 0x92)
        self.assertEqual(decode_sht31(bytes([0x66, 0x66, crc8(b'\x66\x66'), 255, 255, crc8(b'\xff\xff')])),
                         {"temperature": 25.0, "humidity": 100.0})
        with self.assertRaises(ValueError):
            decode_sht31(bytes(6))

    def test_ds18b20_valid_zero_negative_and_crc_failure(self):
        for value in (0, -12375, 25000):
            self.assertEqual(decode_ds18b20(f"aa bb : crc=ff YES\naa bb t={value}\n"), {"temperature": value / 1000})
        for invalid in ("aa NO\naa t=25000", "aa YES\naa", "aa YES\naa t=999000"):
            with self.assertRaises(ValueError):
                decode_ds18b20(invalid)

    def test_discovery_requires_unique_device(self):
        with tempfile.TemporaryDirectory() as root:
            for device in ("28-0001", "28-0002"):
                directory = Path(root) / device
                directory.mkdir()
                (directory / "w1_slave").write_text("aa YES\naa t=22000\n")
            with self.assertRaises(RuntimeError):
                DS18B20(root=root).read()
            self.assertEqual(DS18B20("28-0002", root=root).read(), {"temperature": 22})


class DisplayTests(unittest.TestCase):
    def test_rgb565_matches_reference(self):
        pixels = [(r, g, b) for r in (0, 7, 8, 127, 248, 255)
                  for g in (0, 3, 4, 31, 32, 127, 252, 255)
                  for b in (0, 7, 8, 127, 248, 255)]
        image = Image.new("RGB", (len(pixels), 1))
        image.putdata(pixels)
        expected = b''.join(struct.pack('<H', ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)) for r, g, b in pixels)
        self.assertEqual(rgb565(image), expected)


class APITests(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_paths_payload_and_auth(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value.status = 201
        urlopen.return_value = response
        readings = {"sht31": {"temperature": 22.5, "humidity": 50}, "ds18b20": {"temperature": 0}}
        self.assertEqual(API("https://example.test/", "test-token").send(readings), {"sht31": "ok", "ds18b20": "ok"})
        for call, (sensor, payload) in zip(urlopen.call_args_list, readings.items()):
            request = call.args[0]
            self.assertEqual(request.full_url, f"https://example.test/sensor/{sensor}")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertEqual(json.loads(request.data), payload)
            self.assertEqual(call.kwargs["timeout"], 5)

    @patch("urllib.request.urlopen")
    def test_failures_are_isolated(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value.status = 201
        urlopen.side_effect = [HTTPError("https://example.test", 401, "unauthorized", {}, None), response]
        result = API("https://example.test").send({"sht31": {"temperature": 1, "humidity": 2}, "ds18b20": {"temperature": 3}})
        self.assertEqual(result, {"sht31": "HTTP 401", "ds18b20": "ok"})
        urlopen.side_effect = URLError("offline")
        self.assertEqual(API("https://example.test").send({"ds18b20": {"temperature": 3}}), {"ds18b20": "connection error"})


if __name__ == "__main__":
    unittest.main()
