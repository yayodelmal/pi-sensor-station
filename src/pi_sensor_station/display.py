"""Framebuffer rendering with RGB565 conversion performed by Pillow."""

from pathlib import Path


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
        from .rendering import Renderer

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
        self.last = None
        self.last_image = None

    def draw(self, readings, errors, network, simulated=False, page=0, history=None):
        image = self.renderer.render(readings, errors, network, simulated=simulated, page=page, history=history)
        if image is self.last_image:
            return
        data = rgb565(image)
        if data != self.last:
            with self.device.open("r+b", buffering=0) as framebuffer:
                written = framebuffer.write(data)
                if written != len(data):
                    raise OSError("Incomplete framebuffer write")
            self.last = data
        self.last_image = image
