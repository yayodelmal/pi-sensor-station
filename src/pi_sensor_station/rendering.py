"""Native 480×320 Pillow interpretation of the supplied Monitoreo reference."""

import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .monitor import MonitorConfig, NetworkStatus, decimal, resolve_panels

from .colores import (
    BACKGROUND, PANEL, PANEL_BORDER, TRACK, TEXT, SECONDARY, MUTED,
    OPTIMAL, TARGET_ZONE, TEMPERATURE_ARC, HUMIDITY_ARC, HIGH, LOW,
    DANGER, NO_DATA, NO_DATA_BORDER,
)

BAND = "#173724"

SCALE = 3


class Canvas:
    def __init__(self, size, color, fonts):
        self.image = Image.new("RGB", tuple(v * SCALE for v in size), color)
        self.draw = ImageDraw.Draw(self.image)
        self.fonts = fonts

    def box(self, box):
        return tuple(round(v * SCALE) for v in box)

    def line(self, points, fill, width=1):
        self.draw.line([(round(x * SCALE), round(y * SCALE)) for x, y in points], fill=fill, width=max(1, round(width * SCALE)), joint="curve")

    def ellipse(self, box, fill, outline=None, width=1):
        self.draw.ellipse(self.box(box), fill=fill, outline=outline, width=round(width * SCALE))

    def rounded(self, box, radius, fill, outline=None, width=1):
        self.draw.rounded_rectangle(self.box(box), round(radius * SCALE), fill=fill, outline=outline, width=round(width * SCALE))

    def text_width(self, text, family, size, spacing=0):
        font = self.fonts(family, size)
        return font.getlength(text) / SCALE + spacing * max(0, len(text) - 1)

    def text(self, xy, text, family, size, fill, align="left", spacing=0, max_width=None):
        if max_width is not None:
            while size > 9 and self.text_width(text, family, size, spacing) > max_width:
                size -= 1
        width = self.text_width(text, family, size, spacing)
        x, y = xy
        x -= width / 2 if align == "center" else width if align == "right" else 0
        font = self.fonts(family, size)
        # Align every glyph on one baseline. A tight-top anchor applied to each
        # character pushes accented letters down because their ink starts higher.
        baseline = round(y * SCALE) - font.getbbox("H", anchor="ls")[1]
        if spacing:
            for letter in text:
                self.draw.text((round(x * SCALE), baseline), letter, font=font, fill=fill, anchor="ls")
                x += font.getlength(letter) / SCALE + spacing
        else:
            self.draw.text((round(x * SCALE), baseline), text, font=font, fill=fill, anchor="ls")

    def arc(self, center, radius, start, end, color, width, rounded=False):
        if end <= start:
            return
        x, y = center
        self.draw.arc(self.box((x - radius, y - radius, x + radius, y + radius)), start, end, fill=color, width=round(width * SCALE))
        # Pillow strokes inward, so put caps on the middle of that stroke.
        if rounded:
            cap_radius = width / 2
            for angle in (start, end):
                a = math.radians(angle)
                px, py = x + (radius - cap_radius) * math.cos(a), y + (radius - cap_radius) * math.sin(a)
                self.ellipse((px - cap_radius, py - cap_radius, px + cap_radius, py + cap_radius), color)

    def finish(self):
        return self.image.resize(tuple(v // SCALE for v in self.image.size), Image.Resampling.LANCZOS)


class Renderer:
    def __init__(self, config=None):
        self.config = config or MonitorConfig()
        self.directory = Path(__file__).parent / "assets" / "fonts"
        self._fonts = {}
        self._panels = lru_cache(maxsize=8)(self._panel)
        self._frame_key = None
        self._frame = None
        # Fail at initialization, where a missing font can be reported clearly.
        self.font("Barlow-Regular", 13)
        self.font("Fraunces", 21)

    def font(self, family, size):
        key = family, size
        if key not in self._fonts:
            font = ImageFont.truetype(str(self.directory / (family + ".ttf")), size * SCALE)
            if family == "Fraunces":
                axes = font.get_variation_axes()
                font.set_variation_by_axes([600 if a["name"] == b"Weight" else min(a["maximum"], max(a["minimum"], 21)) if a["name"] == b"Optical Size" else a["default"] for a in axes])
            self._fonts[key] = font
        return self._fonts[key]

    def _panel(self, panel, limits, temperature):
        c = Canvas((228, 268), BACKGROUND, self.font)
        accent = {"ok": OPTIMAL, "high": HIGH, "low": LOW, "disc": DANGER, "nodata": MUTED}[panel.state]
        border = {"ok": PANEL_BORDER, "nodata": NO_DATA_BORDER}.get(panel.state, accent)
        c.rounded((0, 0, 227, 267), 16, PANEL, border)
        c.text((15, 22), "TEMPERATURA" if temperature else "HUMEDAD", "Barlow-SemiBold", 13, MUTED, spacing=1.3)
        label = {"ok": "ÓPTIMA", "high": "ALTA", "low": "BAJA", "disc": "SIN SENSOR", "nodata": "SIN DATO"}[panel.state]
        has_icon = panel.state in ("ok", "high", "low")
        chip_width = math.ceil(c.text_width(label, "Barlow-Bold", 12, 0.5)) + (34 if has_icon else 16)
        chip_x = 213 - chip_width
        filled = panel.state in ("high", "low", "disc")
        c.rounded((chip_x, 13, 213, 38), 13, accent if filled else PANEL, accent)
        fg = BACKGROUND if filled else accent
        if has_icon:
            x, y = chip_x + 8, 21
            if panel.state == "ok":
                c.line([(x, y + 5), (x + 3, y + 8), (x + 10, y + 1)], fg, 2)
            elif panel.state == "high":
                c.line([(x + 5, y + 10), (x + 5, y), (x, y + 5)], fg, 2)
                c.line([(x + 5, y), (x + 10, y + 5)], fg, 2)
            else:
                c.line([(x + 5, y), (x + 5, y + 10), (x, y + 5)], fg, 2)
                c.line([(x + 5, y + 10), (x + 10, y + 5)], fg, 2)
        c.text((chip_x + (26 if has_icon else 8), 21), label, "Barlow-Bold", 12, fg, spacing=0.5)

        center = (114, 142)
        span = limits.scale_max - limits.scale_min
        z0 = (limits.minimum - limits.scale_min) / span
        z1 = (limits.maximum - limits.scale_min) / span
        c.arc(center, 86, 135 + z0 * 270, 135 + z1 * 270, TARGET_ZONE, 4)
        # SVG has r=72 and a centered 14 px stroke; Pillow draws inward from r=79.
        c.arc(center, 79, 135, 405, TRACK, 14, rounded=True)
        if panel.value is not None:
            fraction = max(0, min(1, (panel.value - limits.scale_min) / span))
            end = 135 + fraction * 270
            color = TEMPERATURE_ARC if temperature else HUMIDITY_ARC
            c.arc(center, 79, 135, end, color, 14, rounded=True)
            a = math.radians(end)
            x, y = center[0] + 72 * math.cos(a), center[1] + 72 * math.sin(a)
            c.ellipse((x - 9, y - 9, x + 9, y + 9), TEXT, PANEL, 3)
        number = "—" if panel.value is None else decimal(panel.value) if temperature else str(math.floor(panel.value + 0.5))
        c.text((114, 100), number, "BarlowCondensed-SemiBold", 58, TEXT if panel.value is not None else NO_DATA, align="center", max_width=140)
        c.text((114, 150), "°C" if temperature else "%", "Barlow-SemiBold", 16, MUTED, align="center")
        tag_color = HIGH if panel.fallback else DANGER if panel.state == "disc" else MUTED
        c.text((114, 170), panel.tag, "Barlow-SemiBold", 12, tag_color, align="center", spacing=0.3, max_width=194)
        c.text((72 if temperature else 76, 194), f"{limits.scale_min:g}", "Barlow-Regular", 12, MUTED)
        c.text((156 if temperature else 158, 194), f"{limits.scale_max:g}", "Barlow-Regular", 12, MUTED, align="right")
        c.text((15, 221), panel.note, "Barlow-Medium", 13, MUTED if panel.state == "ok" else accent, max_width=198)
        c.text((15, 241), "Objetivo", "Barlow-Regular", 13, MUTED)
        c.text((213, 241), f"{limits.minimum:g} – {limits.maximum:g} {'°C' if temperature else '%'}", "Barlow-SemiBold", 13, SECONDARY, align="right", max_width=137)
        return c.finish()

    def _summary_card(self, title, panel, limits, samples, temperature):
        c = Canvas((228, 234), BACKGROUND, self.font)
        accent = TEMPERATURE_ARC if temperature else HUMIDITY_ARC
        c.rounded((0, 0, 227, 233), 15, PANEL, PANEL_BORDER)
        c.text((14, 20), title, "Barlow-SemiBold", 13, MUTED, spacing=.6)
        value_color = {"ok": TEXT, "high": HIGH, "low": LOW, "disc": NO_DATA, "nodata": NO_DATA}[panel.state]
        value = "—" if panel.value is None else decimal(panel.value) if temperature else str(math.floor(panel.value + .5))
        c.text((176, 31), value, "BarlowCondensed-SemiBold", 26, value_color, align="right")
        c.text((211, 31), "°C" if temperature else "%", "Barlow-SemiBold", 14, MUTED, align="right")
        x0, x1, y0, y1 = 42, 186, 60, 101
        vals = [v for v in samples if isinstance(v, (int, float))]
        pad = max(limits.maximum - limits.minimum, 1) * .75
        domain0 = min([limits.minimum - pad] + vals)
        domain1 = max([limits.maximum + pad] + vals)
        def py(v): return y1 - (v - domain0) * (y1 - y0) / max(1e-9, domain1 - domain0)
        band_top, band_bottom = py(limits.maximum), py(limits.minimum)
        c.rounded((x0, band_top, x1, band_bottom), 0, BAND)
        for yy in (band_top, band_bottom):
            for xx in range(x0, x1, 6): c.line([(xx, yy), (min(xx + 3, x1), yy)], TARGET_ZONE, 1)
        c.text((38, y0 - 7), decimal(domain1) if temperature else str(round(domain1)), "Barlow-Regular", 10, MUTED, align="right")
        c.text((38, y1 - 5), decimal(domain0) if temperature else str(round(domain0)), "Barlow-Regular", 10, MUTED, align="right")
        previous = None
        step = (x1 - x0) / max(1, len(samples) - 1)
        for i, sample in enumerate(samples):
            point = None if sample is None else (x0 + i * step, py(sample))
            if previous is not None and point is not None: c.line([previous, point], accent, 2)
            previous = point
        if samples and samples[-1] is not None:
            xx = x0 + (len(samples) - 1) * step; yy = py(samples[-1])
            c.ellipse((xx - 4, yy - 4, xx + 4, yy + 4), TEXT, PANEL, 2)
        c.text((x0, 112), "−24 h", "Barlow-Regular", 10, MUTED)
        c.text(((x0+x1)/2, 112), "−12 h", "Barlow-Regular", 10, MUTED, align="center")
        c.text((x1, 112), "ahora", "Barlow-Regular", 10, MUTED, align="right")
        values = [v for v in samples if v is not None]
        if values:
            stats = (min(values), sum(values) / len(values), max(values))
            for x, label, val, align in ((14, "Mín", stats[0], "left"), (114, "Prom", stats[1], "center"), (211, "Máx", stats[2], "right")):
                c.text((x, 148), label, "Barlow-Regular", 12, MUTED, align=align)
                c.text((x, 171), decimal(val) if temperature else str(round(val)), "BarlowCondensed-SemiBold", 21, SECONDARY, align=align)
            pct = round(sum(limits.minimum <= v <= limits.maximum for v in values) * 100 / len(values))
            c.text((14, 195), "En rango · 24 h", "Barlow-SemiBold", 12, SECONDARY)
            c.text((211, 195), f"{pct} %", "Barlow-SemiBold", 12, SECONDARY, align="right")
            c.rounded((14, 211, 212, 219), 4, TRACK)
            if pct: c.rounded((14, 211, 14 + 1.98 * pct, 219), 4, OPTIMAL)
        return c.finish()

    def _summary(self, readings, errors, network, history, clock, now, simulated):
        temperature, humidity = resolve_panels(readings, errors, self.config)
        samples = history or {}
        temp_hist = samples.get("temperature", [None] * 96)
        hum_hist = samples.get("humidity", [None] * 96)
        image = Image.new("RGB", (480, 320), BACKGROUND)
        header = Canvas((480, 44), BACKGROUND, self.font)
        header.ellipse((18,14,35,31), OPTIMAL); header.draw.rectangle(header.box((17,24,36,33)), fill=BACKGROUND)
        header.rounded((24,24,29,32),1,SECONDARY); header.text((48,15),"Monitoreo", "Fraunces",21,TEXT)
        header.text((464,13),clock,"BarlowCondensed-Medium",24,SECONDARY,align="right",spacing=.96)
        label = network.label(now)
        if label:
            color = HIGH if network.state == "fail" else MUTED
            width = min(150, math.ceil(header.text_width(label, "Barlow-SemiBold", 12)) + 16)
            header.rounded((392-width, 9, 392, 34), 12, BACKGROUND, color)
            header.text((392-width/2, 16), label, "Barlow-SemiBold", 12, color, align="center", max_width=width-14)
        else:
            header.ellipse((378,18,388,27),BACKGROUND,OPTIMAL,1.6)
            header.ellipse((382,15,391,26),BACKGROUND,OPTIMAL,1.6)
            header.ellipse((387,19,396,27),BACKGROUND,OPTIMAL,1.6)
            header.draw.rectangle(header.box((382,21,392,26)), fill=BACKGROUND)
            header.line([(381,27),(393,27)],OPTIMAL,1.6)
            header.line([(384,22),(387,24),(391,20)],OPTIMAL,1.6)
        if simulated: header.text((164,20),"DEMO","Barlow-Bold",9,HIGH)
        image.paste(header.finish(),(0,0))
        image.paste(self._summary_card("TEMPERATURA", temperature, self.config.temperature, temp_hist, True),(8,44))
        image.paste(self._summary_card("HUMEDAD", humidity, self.config.humidity, hum_hist, False),(244,44))
        # Compact sensor/API health strip.
        c = Canvas((464,26), PANEL, self.font); c.rounded((0,0,463,25),13,PANEL,PANEL_BORDER)
        statuses = [("DS18B20", errors.get("ds18b20")), ("SHT31", errors.get("sht31")), ("API", network.state)]
        for i,(name,status) in enumerate(statuses):
            x = 12 + i*150; color = OPTIMAL if status in (None,"ok") else DANGER if status == "disc" else HIGH
            c.ellipse((x,8,x+9,17),color)
            c.text((x+14,6),name,"Barlow-Medium",12,SECONDARY)
            suffix = "sin dato" if status == "nodata" else "desconectado" if status == "disc" else "sin conexión" if name == "API" and status == "fail" else "en línea"
            c.text((x+65,6),suffix,"Barlow-Regular",11,color if status in ("disc","fail") else MUTED)
        image.paste(c.finish(),(8,286))
        for x, active in ((232,False),(243,True)):
            ImageDraw.Draw(image).rounded_rectangle((x,313,x+(14 if active else 5),318),2,fill=MUTED if active else NO_DATA_BORDER)
        return image

    def render(self, readings, errors, network=None, clock=None, now=None, simulated=False, page=0, history=None):
        network = network or NetworkStatus()
        clock = clock or datetime.now().strftime("%H:%M")
        label = network.label(now)
        temperature, humidity = resolve_panels(readings, errors, self.config)
        if page == 1:
            key = ("summary", temperature, humidity, network.state, label, clock, simulated,
                   tuple((history or {}).get("temperature", [])), tuple((history or {}).get("humidity", [])))
            if self._frame_key != key:
                self._frame = self._summary(readings, errors, network, history, clock, now, simulated)
                self._frame_key = key
            return self._frame
        key = (temperature, humidity, network.state, label, clock, simulated)
        if self._frame_key == key:
            return self._frame
        c = Canvas((480, 44), BACKGROUND, self.font)
        # Mushroom mark from the reference, approximated with native geometry.
        c.ellipse((18, 14, 35, 31), OPTIMAL)
        c.draw.rectangle(c.box((17, 24, 36, 33)), fill=BACKGROUND)
        c.rounded((24, 24, 29, 32), 1, SECONDARY)
        c.text((48, 15), "Monitoreo", "Fraunces", 21, TEXT)
        if simulated:
            c.text((164, 20), "DEMO", "Barlow-Bold", 9, HIGH)
        c.text((464, 13), clock, "BarlowCondensed-Medium", 24, SECONDARY, align="right", spacing=0.96)
        if label:
            width = min(196, math.ceil(c.text_width(label, "Barlow-SemiBold", 13)) + 18)
            x = 392 - width
            color = HIGH if network.state == "fail" else MUTED
            c.rounded((x, 9, 392, 34), 13, BACKGROUND, color)
            c.text((x + width / 2, 16), label, "Barlow-SemiBold", 13, color, align="center", max_width=width - 16)
        else:
            # Small cloud and tick indicate a completed successful send.
            c.ellipse((378, 18, 388, 27), BACKGROUND, OPTIMAL, 1.6)
            c.ellipse((382, 15, 391, 26), BACKGROUND, OPTIMAL, 1.6)
            c.ellipse((387, 19, 396, 27), BACKGROUND, OPTIMAL, 1.6)
            c.draw.rectangle(c.box((382, 21, 392, 26)), fill=BACKGROUND)
            c.line([(381, 27), (393, 27)], OPTIMAL, 1.6)
            c.line([(384, 22), (387, 24), (391, 20)], OPTIMAL, 1.6)
        image = Image.new("RGB", (480, 320), BACKGROUND)
        image.paste(c.finish(), (0, 0))
        image.paste(self._panels(temperature, self.config.temperature, True), (8, 44))
        image.paste(self._panels(humidity, self.config.humidity, False), (244, 44))
        self._frame_key, self._frame = key, image
        return image
