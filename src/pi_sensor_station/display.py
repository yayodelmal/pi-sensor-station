"""Framebuffer rendering with RGB565 conversion performed by Pillow."""

from pathlib import Path
import fcntl
import os


def rgb565(image):
    from PIL import ImageChops

    red, green, blue = image.convert("RGB").split()
    high = ImageChops.add(red.point(lambda x: x & 0xF8), green.point(lambda x: x >> 5))
    low = ImageChops.add(green.point(lambda x: (x & 0x1C) << 3), blue.point(lambda x: x >> 3))
    data = bytearray(image.width * image.height * 2)
    data[0::2] = low.tobytes()
    data[1::2] = high.tobytes()
    return data


class Display:
    def __init__(self, device, config=None):
        from .render_v2 import Renderer

        self.device = Path(device)
        info = Path("/sys/class/graphics") / self.device.name
        width, height = map(int, (info / "virtual_size").read_text().strip().split(","))
        bits = int((info / "bits_per_pixel").read_text())
        stride = int((info / "stride").read_text())
        if (width, height, bits, stride) != (480, 320, 16, 960):
            raise ValueError("LCD must use 480x320 RGB565 with a 960-byte stride")
        # Matches the fb_ili9486 framebuffer tested on this station.
        if (info / "name").read_text().strip() != "fb_ili9486":
            raise ValueError("Expected the fb_ili9486 framebuffer")
        self.renderer = Renderer(config)
        self.lock_path = Path(os.getenv("FRAMEBUFFER_LOCK", "/run/bootscreen/screen.lock"))
        self.owner_path = self.lock_path.parent / "monitor-active"
        self.last = None
        self.last_image = None

    def draw(self, readings, errors, network, simulated=False, page=0, history=None):
        from PIL import ImageChops

        image = self.renderer.render(readings, errors, network, simulated=simulated, page=page, history=history)
        if image is self.last_image:
            return
        dirty = image.getbbox() if self.last_image is None else ImageChops.difference(image, self.last_image).getbbox()
        if dirty:
            x0, y0, x1, y1 = dirty
            data = rgb565(image.crop(dirty))
            self.lock_path.parent.mkdir(mode=0o775, parents=True, exist_ok=True)
            with self.lock_path.open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                claimed = not self.owner_path.exists()
                try:
                    # Claim ownership while holding the same lock as bootscreen.
                    # Once it sees this marker, bootscreen exits without another draw.
                    self.owner_path.touch()
                    with self.device.open("r+b", buffering=0) as framebuffer:
                        row_bytes = (x1 - x0) * 2
                        for row in range(y1 - y0):
                            framebuffer.seek((y0 + row) * 960 + x0 * 2)
                            start = row * row_bytes
                            written = framebuffer.write(data[start:start + row_bytes])
                            if written != row_bytes:
                                raise OSError("Incomplete framebuffer region write")
                except Exception:
                    if claimed:
                        self.owner_path.unlink(missing_ok=True)
                    raise
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        self.last = dirty
        self.last_image = image

    def close(self):
        self.owner_path.unlink(missing_ok=True)
