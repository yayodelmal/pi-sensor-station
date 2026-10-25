"""Render hardware-free PNG previews: python -m pi_sensor_station.preview."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from .colores import BACKGROUND, TEXT
from .monitor import MonitorConfig, NetworkStatus
from .rendering import Renderer


def scenarios():
    def values(temperature=23, humidity=88):
        return {"ds18b20": {"temperature": temperature}, "sht31": {"temperature": temperature + 0.2, "humidity": humidity}}

    return {
        "optimal": (values(), {}, NetworkStatus("ok")),
        "temperature-high": (values(25.4), {}, NetworkStatus("ok")),
        "temperature-low": (values(20.6), {}, NetworkStatus("ok")),
        "humidity-high": (values(humidity=96), {}, NetworkStatus("ok")),
        "humidity-low": (values(humidity=78), {}, NetworkStatus("ok")),
        "temperature-fallback": (values(23.4), {"ds18b20": "disc"}, NetworkStatus("ok")),
        "sht31-disconnected": (values(), {"sht31": "disc"}, NetworkStatus("ok")),
        "all-disconnected": ({}, {"ds18b20": "disc", "sht31": "disc"}, NetworkStatus("ok")),
        "sht31-no-data": (values(), {"sht31": "nodata"}, NetworkStatus("ok")),
        "all-no-data": ({}, {"ds18b20": "nodata", "sht31": "nodata"}, NetworkStatus("ok")),
        "api-failure": (values(), {}, NetworkStatus("fail", 0)),
        "sensor-and-api-failure": (values(), {"sht31": "disc"}, NetworkStatus("fail", 0)),
        "api-waiting": (values(), {}, NetworkStatus("waiting")),
        "http-disabled": (values(), {}, NetworkStatus("disabled")),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("previews"))
    parser.add_argument("--config", help="Monitor JSON configuration")
    args = parser.parse_args()
    config = MonitorConfig.load(args.config)
    renderer = Renderer(config)
    args.output.mkdir(parents=True, exist_ok=True)
    examples = scenarios()
    sheet = Image.new("RGB", (480 * 2, 348 * ((len(examples) + 1) // 2)), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    for i, (name, (readings, errors, network)) in enumerate(examples.items()):
        image = renderer.render(readings, errors, network, clock="17:28", now=180)
        image.save(args.output / (name + ".png"))
        x, y = (i % 2) * 480, (i // 2) * 348
        sheet.paste(image, (x, y))
        draw.text((x + 8, y + 325), name, fill=TEXT)
    sheet.save(args.output / "scenarios.png")
    print(f"Rendered {len(examples)} scenarios to {args.output}")


if __name__ == "__main__":
    main()
