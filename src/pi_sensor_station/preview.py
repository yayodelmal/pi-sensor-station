"""Render hardware-free PNG previews: python -m pi_sensor_station.preview."""

import argparse
import math
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
    parser.add_argument("--render-golden", type=Path, help="Write 26 deterministic 480x320 scenario PNGs")
    args = parser.parse_args()
    config = MonitorConfig.load(args.config)
    renderer = Renderer(config)
    args.output.mkdir(parents=True, exist_ok=True)
    examples = scenarios()
    if args.render_golden:
        golden = [
            ("00_optimo", examples["optimal"]),
            ("01_temp_alta", examples["temperature-high"]),
            ("02_temp_baja", examples["temperature-low"]),
            ("03_hum_alta", examples["humidity-high"]),
            ("04_hum_baja", examples["humidity-low"]),
            ("05_ds18b20_desc_respaldo", examples["temperature-fallback"]),
            ("06_sht31_desc", examples["sht31-disconnected"]),
            ("07_todos_desc", examples["all-disconnected"]),
            ("08_sht31_sin_lectura", examples["sht31-no-data"]),
            ("09_ambos_sin_lectura", examples["all-no-data"]),
            ("10_api_caida", examples["api-failure"]),
            ("11_sht31_desc_api_caida", examples["sensor-and-api-failure"]),
            ("12_alertas_temp_alta_hum_baja", ({"ds18b20": {"temperature": 25.4}, "sht31": {"temperature": 25.6, "humidity": 78}}, {}, NetworkStatus("ok"))),
        ]
        args.render_golden.mkdir(parents=True, exist_ok=True)
        for name, (readings, errors, network) in golden:
            history = {
                "temperature": [23.1 + .8 * math.sin(i / 11) for i in range(95)] + [
                    readings.get("ds18b20", readings.get("sht31", {})).get("temperature")],
                "humidity": [88 + 5 * math.sin(i / 13) for i in range(95)] + [
                    readings.get("sht31", {}).get("humidity")],
            }
            for page, suffix in ((0, "inicio"), (1, "resumen")):
                image = renderer.render(readings, errors, network, clock="17:28", now=180,
                                        page=page, history=history)
                image.save(args.render_golden / f"{name}__{suffix}.png")
        print(f"Rendered 26 scenario images to {args.render_golden}")
        return
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
