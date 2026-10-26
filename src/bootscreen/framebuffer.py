import contextlib
import fcntl
import os
import struct
import time
from pathlib import Path

from .render import to_rgb565


class Framebuffer:
    monitor_owner_path = Path("/run/bootscreen/monitor-active")

    def __init__(self, device, lock_path="/run/bootscreen/screen.lock"):
        self.device = Path(device)
        info = Path("/sys/class/graphics") / self.device.name
        self.stride = int((info / "stride").read_text())
        self.width, self.height = map(int, (info / "virtual_size").read_text().strip().split(","))
        if (self.width, self.height, self.stride, int((info / "bits_per_pixel").read_text())) != (480, 320, 960, 16):
            raise ValueError("Expected 480x320, 16 bpp and a 960-byte stride")
        self.fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        try:
            variable = bytearray(160)
            fcntl.ioctl(self.fd, 0x4600, variable, True)  # FBIOGET_VSCREENINFO
            values = struct.unpack_from("<20I", variable)
            if values[:2] != (480, 320) or values[4:8] != (0, 0, 16, 0):
                raise ValueError("Unsupported visible framebuffer geometry/offset")
            if values[8:20] != (11, 5, 0, 5, 6, 0, 0, 5, 0, 0, 0, 0):
                raise ValueError("Framebuffer must use RGB565 without alpha")
            self.lock_path = Path(lock_path)
            self.lock_path.parent.mkdir(mode=0o775, parents=True, exist_ok=True)
            self.lock = self.lock_path.open("a+b")
            os.chmod(self.lock_path, 0o660)
        except Exception:
            os.close(self.fd)
            raise
        self.last = None
        self.last_rgb = None
        self.rows_written = 0
        self.last_write_seconds = 0

    def close(self):
        self.lock.close()
        os.close(self.fd)

    def _write(self, data, force=False, dirty_rows=None):
        if len(data) != self.stride * self.height:
            raise ValueError("Wrong framebuffer byte count")
        rows = []
        candidates = range(self.height) if dirty_rows is None else sorted(set(dirty_rows))
        for row in candidates:
            start, end = row * self.stride, (row + 1) * self.stride
            if force or self.last is None or data[start:end] != self.last[start:end]:
                rows.append(row)
        rows = sorted(set(rows))
        # Coalesce adjacent dirty rows into writes, preserving the real stride.
        self.rows_written = len(rows)
        first = 0
        while first < len(rows):
            last = first
            while last + 1 < len(rows) and rows[last + 1] == rows[last] + 1:
                last += 1
            offset = rows[first] * self.stride
            block = memoryview(data)[offset:(rows[last] + 1) * self.stride]
            written = 0
            while written < len(block):
                count = os.pwrite(self.fd, block[written:], offset + written)
                if count <= 0:
                    raise OSError("Incomplete framebuffer write")
                written += count
            first = last + 1
        self.last = bytearray(data)

    def _write_regions(self, image, rgb, regions):
        """Convert and write only changed pixel rectangles from the RGB cache."""
        boxes = []
        for x0, y0, x1, y1 in regions.values():
            box = (max(0, int(x0)), max(0, int(y0)), min(self.width, int(x1)), min(self.height, int(y1)))
            if box[0] < box[2] and box[1] < box[3]:
                boxes.append(box)
        # Merge overlapping boxes to avoid duplicate conversion/writes.
        merged = []
        for box in boxes:
            x0, y0, x1, y1 = box
            changed = True
            while changed:
                changed = False
                for i, (a, b, c, d) in enumerate(merged):
                    if x0 < c and a < x1 and y0 < d and b < y1:
                        x0, y0, x1, y1 = min(x0, a), min(y0, b), max(x1, c), max(y1, d)
                        merged.pop(i)
                        changed = True
                        break
            merged.append((x0, y0, x1, y1))

        previous_rgb = self.last_rgb
        updates = []
        dirty_rows = set()
        rgb_pitch = self.width * 3
        for x0, y0, x1, y1 in merged:
            crop = image.crop((x0, y0, x1, y1))
            crop_rgb = crop.tobytes()
            packed = to_rgb565(crop)
            row_pixels = x1 - x0
            row_bytes = row_pixels * 2
            for y in range(y0, y1):
                rgb_offset = y * rgb_pitch + x0 * 3
                rgb_end = rgb_offset + row_pixels * 3
                crop_offset = (y - y0) * row_pixels * 3
                crop_end = crop_offset + row_pixels * 3
                if crop_rgb[crop_offset:crop_end] == previous_rgb[rgb_offset:rgb_end]:
                    continue
                source_offset = (y - y0) * row_bytes
                packed_row = packed[source_offset:source_offset + row_bytes]
                target_offset = y * self.stride + x0 * 2
                self.last[target_offset:target_offset + row_bytes] = packed_row
                previous_rgb[rgb_offset:rgb_end] = crop_rgb[crop_offset:crop_end]
                updates.append((y, x0, x1, packed_row))
                dirty_rows.add(y)

        started = time.monotonic()
        for y, x0, _x1, block in updates:
            offset = y * self.stride + x0 * 2
            written = 0
            while written < len(block):
                count = os.pwrite(self.fd, block[written:], offset + written)
                if count <= 0:
                    raise OSError("Incomplete framebuffer region write")
                written += count
        return len(dirty_rows), time.monotonic() - started

    def draw(self, image, force=False, leased=False, regions=None, stop_if_monitor=False):
        if not leased:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return None
        started = time.monotonic()
        try:
            if stop_if_monitor and self.monitor_owner_path.exists():
                return None
            full_frame = self.last_rgb is None or self.last is None or force
            if full_frame:
                data = to_rgb565(image)
                write_started = time.monotonic()
                self._write(data, force)
                self.last_write_seconds = time.monotonic() - write_started
                self.last_rgb = bytearray(image.tobytes())
            elif regions is None:
                data = to_rgb565(image)
                write_started = time.monotonic()
                self._write(data, force)
                self.last_write_seconds = time.monotonic() - write_started
                self.last_rgb = bytearray(image.tobytes())
            else:
                self.rows_written, self.last_write_seconds = self._write_regions(image, None, regions)
        finally:
            if not leased:
                fcntl.flock(self.lock, fcntl.LOCK_UN)
        return time.monotonic() - started

    @contextlib.contextmanager
    def preview(self):
        """Temporarily own the display; restore prior bytes without stopping a service."""
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        previous = os.pread(self.fd, self.stride * self.height, 0)
        if len(previous) != self.stride * self.height:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            raise OSError("Could not save the framebuffer for preview")
        try:
            self.last = None
            yield
        finally:
            try:
                self._write(previous, force=True)
                self.last_rgb = None
            finally:
                fcntl.flock(self.lock, fcntl.LOCK_UN)
