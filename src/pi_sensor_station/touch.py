"""Raw Linux evdev touch reader and horizontal page gesture recognizer."""

import os
import struct
import time
from pathlib import Path


class Swipe:
    def __init__(self):
        self.start = self.last = None
        self.position = (0, 0)
        self.down = False

    def feed(self, x, y, down, now=None):
        now = time.monotonic() if now is None else now
        if down and not self.down:
            self.start = self.last = (x, y, now)
        elif down and self.start:
            self.last = (x, y, now)
        elif not down and self.down and self.start:
            sx, sy, st = self.start
            dx, dy = x - sx, y - sy
            duration = max(1, (now - st) * 1000)
            velocity = abs(dx) / duration
            result = (1 if dx < 0 else -1) if abs(dx) > 60 or (abs(dx) > 20 and velocity > .5) else 0
            if abs(dx) <= 8 or abs(dx) <= 1.5 * abs(dy):
                result = 0
            self.start = self.last = None
            self.down = False
            return result
        self.position = (x, y)
        self.down = bool(down)
        return 0


class TouchReader:
    """Reads type-B compatible single-touch events from /dev/input/eventN."""
    EVENT = struct.Struct("llHHi")

    def __init__(self, device=None, raw_x=(0, 4095), raw_y=(0, 4095), rotation=0):
        self.device = Path(device) if device else self.find_device()
        self.raw_x, self.raw_y, self.rotation = raw_x, raw_y, rotation % 360
        self.fd = os.open(self.device, os.O_RDONLY | os.O_NONBLOCK)
        self.x = self.y = 0
        self.down = False
        self.swipe = Swipe()

    @staticmethod
    def find_device():
        devices = []
        for node in sorted(Path("/dev/input").glob("event*")):
            capabilities = Path("/sys/class/input") / node.name / "device/capabilities/abs"
            try:
                has_absolute_axes = int(capabilities.read_text().strip(), 16) != 0
            except (OSError, ValueError):
                has_absolute_axes = False
            if has_absolute_axes:
                devices.append(node)
        if not devices:
            raise FileNotFoundError("no absolute-axis touch device in /dev/input")
        return devices[0]

    @staticmethod
    def _map(value, bounds, maximum):
        low, high = bounds
        return max(0, min(maximum, round((value - low) * maximum / max(1, high - low))))

    def _point(self):
        x = self._map(self.x, self.raw_x, 479)
        y = self._map(self.y, self.raw_y, 319)
        if self.rotation == 90:
            x, y = 479 - y, x * 319 // 479
        elif self.rotation == 180:
            x, y = 479 - x, 319 - y
        elif self.rotation == 270:
            x, y = y * 479 // 319, 319 - x * 319 // 479
        return x, y

    def poll(self):
        actions = []
        while True:
            try:
                data = os.read(self.fd, self.EVENT.size * 32)
            except BlockingIOError:
                break
            if not data:
                break
            for offset in range(0, len(data) - self.EVENT.size + 1, self.EVENT.size):
                seconds, micros, kind, code, value = self.EVENT.unpack_from(data, offset)
                event_time = seconds + micros / 1_000_000
                if kind == 3 and code in (0, 53): self.x = value
                elif kind == 3 and code in (1, 54): self.y = value
                elif kind == 1 and code == 330: self.down = bool(value)
                elif kind == 0:
                    x, y = self._point()
                    action = self.swipe.feed(x, y, self.down, event_time)
                    if action: actions.append(action)
        return actions

    def close(self):
        os.close(self.fd)
