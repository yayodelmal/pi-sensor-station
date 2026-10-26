import importlib.util
import json
import os
import socket
import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageChops

from bootscreen.config import AnimationConfig, Check, Config
from bootscreen.framebuffer import Framebuffer
from bootscreen.probes import Snapshot, network_address
from bootscreen.render import (ACTIVE, FAILED, OK, SKIPPED, CachedRenderer, demo_frames,
                               demo_screens, layout_regions, render, render_partial, to_rgb565)
from bootscreen.__main__ import changed_regions
from bootscreen.state import AnimationPlan, Controller
from pi_sensor_station.notify import ready

ROOT = Path(__file__).resolve().parents[1]


def snapshot(system=True, wifi=False, services=False, app=False):
    return Snapshot({"basic.target": system, "ssh.service": services,
                     "avahi-daemon.service": services, "pi-sensor-station.service": app},
                    wifi, "192.168.100.17" if wifi else "")


class StateTests(unittest.TestCase):
    def test_timeout_countdown_zero_retry_and_recovery_do_not_reset_uptime(self):
        controller = Controller(Config())
        controller.update(10, snapshot())
        self.assertEqual(controller.screen(10).steps[1].status, ACTIVE)
        controller.update(70, snapshot())
        self.assertEqual(controller.screen(70).steps[1].status, FAILED)
        self.assertEqual(controller.screen(70).retry_in, 8)
        controller.update(78, snapshot(wifi=True))
        self.assertEqual(controller.screen(78).retry_in, 0)
        controller.update(78.1, snapshot(wifi=True, services=True))
        self.assertEqual(controller.screen(78.1).title, "CASI LISTO")
        controller.update(80, snapshot(wifi=True, services=True, app=True))
        self.assertEqual(controller.screen(80).title, "LISTO")
        self.assertEqual(controller.screen(999).elapsed, 80)
        self.assertEqual(controller.screen(999).ip, "192.168.100.17")

    def test_missing_app_never_reports_ready(self):
        controller = Controller(Config())
        controller.update(100, snapshot(wifi=True, services=True))
        self.assertEqual(controller.index, 3)
        self.assertIsNone(controller.ready_at)
        controller.update(160, snapshot(wifi=True, services=True))
        self.assertEqual(controller.screen(160).title, "ERROR")

    def test_delayed_poll_still_exposes_zero_before_recovery(self):
        controller = Controller(Config())
        controller.update(10, snapshot())
        controller.update(70, snapshot())
        controller.update(78.5, snapshot(wifi=True, services=True, app=True))
        self.assertEqual(controller.screen(78.5).retry_in, 0)
        self.assertIsNone(controller.ready_at)
        controller.update(80, snapshot(wifi=True, services=True, app=True))
        self.assertEqual(controller.screen(80).mode, "ready")

    def test_network_regression_before_ready_restarts_wifi(self):
        controller = Controller(Config())
        controller.update(100, snapshot(wifi=True, services=True))
        controller.update(101, snapshot(wifi=False, services=True))
        self.assertEqual(controller.index, 1)
        self.assertEqual(controller.screen(101).steps[1].status, ACTIVE)

    def test_disabled_step_is_marked_skipped_not_a_successful_check(self):
        config = Config()
        config = replace(config, steps=(*config.steps[:3], replace(config.steps[3], enabled=False)))
        controller = Controller(config)
        controller.update(100, snapshot(wifi=True, services=True))
        self.assertEqual(controller.screen(100).mode, "ready")
        self.assertEqual(controller.screen(100).steps[3].status, SKIPPED)

    def test_no_blink_and_frozen_ready_do_not_change_frames(self):
        controller = Controller(Config(blink=False))
        controller.update(10, snapshot(wifi=True, services=True, app=True))
        self.assertEqual(render(controller.screen(20)).tobytes(), render(controller.screen(21)).tobytes())


class ProbeTests(unittest.TestCase):
    def test_network_requires_ipv4_and_default_route_on_selected_interface(self):
        addresses = [{"ifname": "wlan0", "addr_info": [{"family": "inet", "scope": "global", "local": "192.168.100.17"}]}]
        routes = [{"dst": "default", "dev": "wlan0"}]
        self.assertEqual(network_address(addresses, routes, "wlan0"), "192.168.100.17")
        self.assertEqual(network_address(addresses, [{"dst": "default"}], "wlan0"), "192.168.100.17")
        self.assertEqual(network_address(addresses, [], "wlan0"), "")
        self.assertEqual(network_address(addresses, [{"dst": "default", "dev": "eth0"}], "wlan0"), "")
        addresses[0]["addr_info"][0]["local"] = "169.254.1.2"
        self.assertEqual(network_address(addresses, routes, "wlan0"), "")

    def test_systemd_waits_for_all_units_to_be_active(self):
        check = Check("Servicios", "systemd", ("ssh.service", "avahi-daemon.service"))
        self.assertFalse(Snapshot({"ssh.service": True}).ready(check))
        self.assertTrue(Snapshot({"ssh.service": True, "avahi-daemon.service": True}).ready(check))

    def test_deployment_config_matches_agreed_checks(self):
        config = Config.load(ROOT / "deploy/bootscreen/config.toml")
        self.assertEqual(config.interface, "wlan0")
        self.assertEqual(config.steps[0].units, ("basic.target",))
        self.assertEqual(config.steps[2].units, ("ssh.service", "avahi-daemon.service"))
        self.assertEqual(config.steps[3].units, ("pi-sensor-station.service",))
        self.assertEqual(config.animations.max_fps, 5)
        self.assertTrue(config.animations.enabled)
        self.assertFalse(config.animations.ready_intro)
        self.assertFalse(config.blink)
        with self.assertRaises(ValueError):
            Check("App", "systemd", ("--bad",))
        with self.assertRaises(ValueError):
            Config(interface="-bad")


class FrameTests(unittest.TestCase):
    def test_cached_clock_and_countdown_match_the_full_renderer(self):
        renderer = CachedRenderer()
        for screen in demo_screens().values():
            for elapsed in (1, 59, 61, 152):
                current = replace(screen, elapsed=elapsed, retry_in=elapsed % 9)
                self.assertEqual(renderer(current).tobytes(), render(current).tobytes())

    def test_rgb_row_cache_matches_full_conversion_after_multiple_updates(self):
        with tempfile.TemporaryFile() as handle:
            fb = object.__new__(Framebuffer)
            fb.fd, fb.stride, fb.width, fb.height = handle.fileno(), 960, 480, 320
            fb.last = fb.last_rgb = None
            renderer = CachedRenderer()
            original = demo_screens()["01-iniciando"]
            for elapsed in (1, 2, 3):
                image = renderer(replace(original, elapsed=elapsed))
                fb.draw(image, leased=True)
                self.assertEqual(os.pread(fb.fd, 307200, 0), to_rgb565(image))
                if elapsed > 1:
                    self.assertLess(fb.rows_written, 30)

    def test_region_write_only_converts_and_writes_named_rows(self):
        with tempfile.TemporaryFile() as handle:
            fb = object.__new__(Framebuffer)
            fb.fd, fb.stride, fb.width, fb.height = handle.fileno(), 960, 480, 320
            fb.last = fb.last_rgb = None
            first = render(demo_screens()["01-iniciando"])
            fb.draw(first, leased=True)
            second = render(replace(demo_screens()["01-iniciando"], dots=2))
            regions = {}
            render(replace(demo_screens()["01-iniciando"], dots=2), regions=regions)
            fb.draw(second, leased=True, regions={"dots": regions["dots"]})
            self.assertEqual(os.pread(fb.fd, 307200, 0), to_rgb565(second))
            self.assertLess(fb.rows_written, 20)

    def test_reference_animation_frames_stay_close_to_supplied_pngs(self):
        for name, screen in demo_frames().items():
            with self.subTest(name=name):
                actual = render(screen)
                with Image.open(ROOT / "design/bootscreen-reference/anim" / (name + ".png")) as reference:
                    delta = ImageChops.difference(actual, reference.convert("RGB")).convert("L")
                    different = sum(delta.histogram()[1:])
                self.assertLess(different / (480 * 320), 0.06)

    def test_partial_frame_matches_full_render_for_every_animation_region(self):
        boot = demo_screens()["01-iniciando"]
        ready = demo_screens()["03-listo"]
        error = demo_screens()["04-error"]
        cases = [
            (boot, replace(boot, dots=2)),
            (boot, replace(boot, blink_on=False, cursor_on=False)),
            (boot, replace(boot, elapsed=24)),
            (boot, demo_screens()["02-casi-listo"]),
            (boot, replace(boot, flash_rows=(0,))),
            (ready, replace(ready, reveal=2)),
            (ready, replace(ready, sweep=0.5)),
            (ready, replace(ready, show_ip=False)),
            (ready, replace(ready, cursor_on=False)),
            (error, replace(error, strip_on=False)),
            (error, replace(error, retry_in=7)),
        ]
        for before, after in cases:
            with self.subTest(before=before.mode, after=after.title):
                areas = layout_regions(after)
                dirty = changed_regions(before, after, areas)
                partial = render_partial(after, render(before), dirty, areas)
                self.assertEqual(partial.tobytes(), render(after).tobytes())

    def test_ready_cursor_blink_dirties_only_cursor_rows(self):
        ready = demo_screens()["03-listo"]
        changed = replace(ready, cursor_on=False)
        regions = layout_regions(changed)
        dirty = changed_regions(ready, changed, regions)
        self.assertEqual(set(dirty), {"cursor"})


class AnimationTests(unittest.TestCase):
    def test_monotonic_points_blink_and_flash_phases(self):
        planner = AnimationPlan(Config(), started=10.0)
        screen = demo_screens()["01-iniciando"]
        planner.update(screen, 10.0)
        self.assertEqual(screen.dots, 0)
        self.assertTrue(screen.cursor_on)
        planner.update(screen, 10.4)
        self.assertEqual(screen.dots, 1)
        planner.update(screen, 10.5)
        self.assertFalse(screen.cursor_on)
        screen.steps[1].status = OK
        planner.update(screen, 10.6)
        self.assertEqual(screen.flash_rows, (1,))
        planner.update(screen, 10.96)
        self.assertEqual(screen.flash_rows, ())

    def test_ready_intro_uses_all_bar_steps_and_delays_ip(self):
        planner = AnimationPlan(Config(), started=0.0)
        screen = demo_screens()["03-listo"]
        planner.update(screen, 1.0)
        self.assertEqual((screen.reveal, screen.sweep, screen.show_ip), (0, 0.0, False))
        planner.update(screen, 1.9)
        self.assertEqual((screen.reveal, screen.sweep, screen.show_ip), (5, 1.0, False))
        planner.update(screen, 1.96)
        self.assertTrue(screen.show_ip)

    def test_animation_switches_off_all_motion(self):
        config = Config(animations=AnimationConfig(enabled=False))
        planner = AnimationPlan(config, started=0.0)
        screen = demo_screens()["01-iniciando"]
        planner.update(screen, 0.7)
        self.assertEqual((screen.cursor_on, screen.blink_on, screen.dots), (True, True, 3))
        screen = demo_screens()["03-listo"]
        planner.update(screen, 1.0)
        self.assertEqual((screen.reveal, screen.sweep, screen.show_ip), (5, 1.0, True))

    def test_renderer_stays_close_to_supplied_reference(self):
        for name, screen in demo_screens().items():
            with self.subTest(name=name):
                actual = render(screen)
                with Image.open(ROOT / "design/bootscreen-reference" / (name + ".png")) as reference:
                    delta = ImageChops.difference(actual, reference.convert("RGB")).convert("L")
                    different = sum(delta.histogram()[1:])
                self.assertLess(different / (480 * 320), 0.06)
                self.assertEqual(actual.size, (480, 320))

    def test_fast_conversion_matches_reference_rgb565(self):
        image = render(demo_screens()["04-error"])
        raw = image.tobytes()
        expected = b''.join(struct.pack('<H', ((raw[i] & 0xF8) << 8) | ((raw[i+1] & 0xFC) << 3) | (raw[i+2] >> 3)) for i in range(0, len(raw), 3))
        self.assertEqual(to_rgb565(image), expected)

    def test_dirty_writes_preserve_all_other_rows_and_skip_identical_frames(self):
        with tempfile.TemporaryFile() as handle:
            framebuffer = object.__new__(Framebuffer)
            framebuffer.fd, framebuffer.stride, framebuffer.height = handle.fileno(), 960, 320
            framebuffer.last = None
            first = bytes(960 * 320)
            framebuffer._write(first)
            self.assertEqual(framebuffer.rows_written, 320)
            framebuffer._write(first)
            self.assertEqual(framebuffer.rows_written, 0)
            changed = bytearray(first)
            changed[19 * 960:21 * 960] = b'\x7f' * (2 * 960)
            framebuffer._write(bytes(changed))
            self.assertEqual(framebuffer.rows_written, 2)
            self.assertEqual(os.pread(handle.fileno(), 960 * 320, 0), changed)

    def test_monitor_owner_marker_stops_bootscreen_frame_under_shared_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "monitor-active"
            marker.touch()
            with (root / "screen.lock").open("a+b") as lock, tempfile.TemporaryFile() as fb_file:
                fb = object.__new__(Framebuffer)
                fb.fd, fb.stride, fb.width, fb.height = fb_file.fileno(), 960, 480, 320
                fb.lock, fb.monitor_owner_path = lock, marker
                self.assertIsNone(fb.draw(render(demo_screens()["03-listo"]), stop_if_monitor=True))
                self.assertEqual(os.fstat(fb.fd).st_size, 0)


class DisplayHandoffTests(unittest.TestCase):
    def test_monitor_claims_and_releases_the_shared_framebuffer_owner_marker(self):
        from bootscreen.render import Image
        from pi_sensor_station.display import Display

        class StaticRenderer:
            def render(self, *args, **kwargs):
                return Image.new("RGB", (480, 320), "white")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fb_path = root / "fb"
            fb_path.write_bytes(bytes(480 * 320 * 2))
            lock_path = root / "screen.lock"
            display = object.__new__(Display)
            display.renderer = StaticRenderer()
            display.device = fb_path
            display.lock_path = lock_path
            display.owner_path = root / "monitor-active"
            display.last = display.last_image = None
            display.draw({}, {}, None)
            self.assertTrue(display.owner_path.exists())
            self.assertEqual(fb_path.stat().st_size, 480 * 320 * 2)
            display.close()
            self.assertFalse(display.owner_path.exists())


class InstallTests(unittest.TestCase):
    def test_quiet_flags_keep_both_rescue_consoles_and_root_arguments(self):
        spec = importlib.util.spec_from_file_location("bootscreen_install", ROOT / "deploy/bootscreen/install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        original = "console=serial0,115200 console=tty1 root=PARTUUID=test rootwait loglevel=7 splash\n"
        result = installer.quiet_cmdline(original)
        self.assertIn("console=serial0,115200", result)
        self.assertIn("console=tty1", result)
        self.assertIn("root=PARTUUID=test", result)
        self.assertIn("fbcon=map:0", result)
        self.assertNotIn("loglevel=7", result)
        self.assertEqual(installer.quiet_cmdline(result), result)

    def test_boot_unit_does_not_order_other_startup_units_after_itself(self):
        unit = (ROOT / "deploy/bootscreen/bootscreen.service").read_text()
        self.assertIn("DefaultDependencies=no", unit)
        self.assertIn("Type=simple", unit)
        self.assertNotIn("Before=", unit)
        self.assertNotIn("network-online.target", unit)

    def test_station_notifies_only_via_configured_systemd_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "notify.sock")
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
                    receiver.bind(path)
                    receiver.settimeout(1)
                    previous = os.environ.get("NOTIFY_SOCKET")
                    os.environ["NOTIFY_SOCKET"] = path
                    try:
                        ready()
                        self.assertIn(b"READY=1", receiver.recv(512))
                    finally:
                        if previous is None:
                            os.environ.pop("NOTIFY_SOCKET", None)
                        else:
                            os.environ["NOTIFY_SOCKET"] = previous
            except PermissionError:
                self.skipTest("Sandbox blocks local Unix sockets")


if __name__ == "__main__":
    unittest.main()
