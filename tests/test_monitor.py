import errno
import json
import tempfile
import unittest
from pathlib import Path

from pi_sensor_station.monitor import MonitorConfig, NetworkStatus, Range, error_status, resolve_panels
from pi_sensor_station.preview import scenarios
from pi_sensor_station.rendering import Canvas, Renderer, SCALE
from pi_sensor_station.sensors import SensorDisconnected


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.readings = {"ds18b20": {"temperature": 23}, "sht31": {"temperature": 25.4, "humidity": 88}}

    def test_primary_and_fallback_use_real_sensor_values(self):
        config = MonitorConfig()
        primary, humidity = resolve_panels(self.readings, {}, config)
        self.assertEqual((primary.state, primary.value, primary.tag), ("ok", 23, "DS18B20"))
        self.assertEqual(humidity.state, "ok")
        fallback, _ = resolve_panels(self.readings, {"ds18b20": "disc"}, config)
        self.assertEqual((fallback.state, fallback.value, fallback.fallback), ("high", 25.4, True))
        self.assertEqual(fallback.note, "+1,4 sobre el máximo")
        reversed_source, _ = resolve_panels(self.readings, {}, MonitorConfig(temperature_source="sht31"))
        self.assertEqual(reversed_source.value, 25.4)

    def test_fallback_can_be_disabled_for_different_probe_locations(self):
        temperature, _ = resolve_panels(self.readings, {"ds18b20": "disc"}, MonitorConfig(temperature_fallback=False))
        self.assertIsNone(temperature.value)
        self.assertEqual(temperature.state, "disc")

    def test_invalid_and_missing_values_are_never_displayed_as_current(self):
        for value in (float("nan"), float("inf"), None, -100, 200, True):
            readings = {"ds18b20": {"temperature": value}, "sht31": {"temperature": value, "humidity": value}}
            temperature, humidity = resolve_panels(readings, {}, MonitorConfig())
            self.assertEqual((temperature.state, humidity.state), ("nodata", "nodata"))
        temperature, humidity = resolve_panels({}, {"ds18b20": "disc", "sht31": "disc"}, MonitorConfig())
        self.assertEqual((temperature.state, humidity.state), ("disc", "disc"))
        temperature, _ = resolve_panels({}, {"ds18b20": "disc", "sht31": "nodata"}, MonitorConfig())
        self.assertEqual(temperature.state, "nodata")

    def test_target_boundaries_are_inclusive(self):
        for value, state in ((21.9, "low"), (22, "ok"), (24, "ok"), (24.1, "high")):
            self.readings["ds18b20"]["temperature"] = value
            self.assertEqual(resolve_panels(self.readings, {}, MonitorConfig())[0].state, state)
        self.readings["ds18b20"]["temperature"] = 0
        self.assertEqual(resolve_panels(self.readings, {}, MonitorConfig())[0].value, 0)

    def test_errors_distinguish_absence_from_crc_or_bus_configuration(self):
        self.assertEqual(error_status(SensorDisconnected()), "disc")
        self.assertEqual(error_status(OSError(errno.EREMOTEIO, "No ACK")), "disc")
        self.assertEqual(error_status(ValueError("bad CRC")), "nodata")
        self.assertEqual(error_status(FileNotFoundError("No I2C adapter")), "nodata")

    def test_bad_configuration_is_rejected(self):
        for values in ((22, 22, 16, 32), (22, 24, 25, 32), (22, float("nan"), 16, 32)):
            with self.assertRaises(ValueError):
                Range(*values)
        with self.assertRaises(ValueError):
            MonitorConfig(temperature_fallback="false")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.json"
            path.write_text(json.dumps({"temperature_source": "sht31", "temperature_fallback": False}))
            self.assertEqual(MonitorConfig.load(path).temperature_source, "sht31")
            path.write_text('{"humidity": {"minimum": 99}}')
            with self.assertRaises(ValueError):
                MonitorConfig.load(path)

    def test_network_wait_failure_duration_and_recovery(self):
        network = NetworkStatus()
        self.assertEqual(network.label(), "API pendiente")
        network.update({"sht31": "connection error"}, now=0)
        self.assertEqual(network.label(now=20), "API sin envío · <1 min")
        network.update({"sht31": "HTTP 401", "ds18b20": "ok"}, now=120)
        self.assertEqual(network.label(now=180), "API sin envío · 3 min")
        network.update({"sht31": "ok", "ds18b20": "ok"}, now=200)
        self.assertEqual(network.state, "ok")
        self.assertIsNone(network.failed_since)
        self.assertEqual(network.label(), "")


class RenderingTests(unittest.TestCase):
    def test_accents_extend_upward_without_lowering_the_letter(self):
        renderer = Renderer()
        for accented, plain in (("Ó", "O"), ("Á", "A"), ("ñ", "n")):
            with self.subTest(letter=accented):
                canvas = Canvas((100, 80), "black", renderer.font)
                font = renderer.font("Barlow-Bold", 24)
                canvas.text((10, 20), accented + plain, "Barlow-Bold", 24, "white", spacing=2)
                second_x = round(10 * SCALE + font.getlength(accented) + 2 * SCALE)
                first = canvas.image.crop((10 * SCALE, 0, second_x, 80 * SCALE)).getbbox()
                second = canvas.image.crop((second_x, 0, 100 * SCALE, 80 * SCALE)).getbbox()
                self.assertEqual(first[3], second[3], "Accented and plain glyphs must share the same baseline")
                self.assertLess(first[1], second[1], "The accent must extend above the plain glyph")

    def test_unchanged_frames_skip_rendering_and_reading_changes_invalidate_cache(self):
        renderer = Renderer()
        readings, errors, network = scenarios()["optimal"]
        first = renderer.render(readings, errors, network, clock="17:28")
        self.assertIs(first, renderer.render(readings, errors, network, clock="17:28"))
        readings["ds18b20"]["temperature"] = 25
        updated = renderer.render(readings, errors, network, clock="17:28")
        self.assertIsNot(first, updated)
        self.assertNotEqual(first.tobytes(), updated.tobytes())

    def test_reference_scenarios_render_with_bundled_fonts(self):
        renderer = Renderer()
        for name, (readings, errors, network) in scenarios().items():
            with self.subTest(name=name):
                image = renderer.render(readings, errors, network, clock="17:28", now=180)
                self.assertEqual(image.size, (480, 320))
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertLessEqual(renderer._panels.cache_info().currsize, 8)

    def test_network_failure_changes_header_but_not_measurements(self):
        renderer = Renderer()
        readings, errors, _ = scenarios()["optimal"]
        ok = renderer.render(readings, errors, NetworkStatus("ok"), clock="17:28")
        fail = renderer.render(readings, errors, NetworkStatus("fail", 0), clock="17:28", now=180)
        self.assertEqual(ok.crop((0, 44, 480, 320)).tobytes(), fail.crop((0, 44, 480, 320)).tobytes())
        self.assertNotEqual(ok.tobytes(), fail.tobytes())


if __name__ == "__main__":
    unittest.main()
