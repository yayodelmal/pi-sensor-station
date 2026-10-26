"""Render hardware-free PNG previews: python -m pi_sensor_station.preview."""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

from .colores import BACKGROUND, TEXT
from .monitor import MonitorConfig, NetworkStatus
from .render_v2 import Renderer


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
        good = examples["optimal"]
        golden = [
            ("00_optimo", good), ("01_temp_alta", examples["temperature-high"]),
            ("02_temp_baja", examples["temperature-low"]), ("03_hum_alta", examples["humidity-high"]),
            ("04_hum_baja", examples["humidity-low"]),
            ("05_sustrato_alto", ({"ds18b20":{"temperature":26.6},"sht31":{"temperature":23.2,"humidity":88}}, {}, NetworkStatus("ok"))),
            ("06_sustrato_bajo", ({"ds18b20":{"temperature":19.4},"sht31":{"temperature":23.2,"humidity":88}}, {}, NetworkStatus("ok"))),
            ("07_ds18b20_desc", ({"sht31":{"temperature":23.2,"humidity":88}}, {"ds18b20":"disc"}, NetworkStatus("ok"))),
            ("08_sht31_desc", ({"ds18b20":{"temperature":23.5}}, {"sht31":"disc"}, NetworkStatus("ok"))),
            ("09_ambos_desc", ({}, {"sht31":"disc","ds18b20":"disc"}, NetworkStatus("ok"))),
            ("10_sht31_sin_lectura", ({"ds18b20":{"temperature":23.5}}, {"sht31":"nodata"}, NetworkStatus("ok"))),
            ("11_ds18b20_sin_lectura", ({"sht31":{"temperature":23.2,"humidity":88}}, {"ds18b20":"nodata"}, NetworkStatus("ok"))),
            ("12_api_caida", (good[0], good[1], NetworkStatus("fail", 0))),
            ("13_sht31_desc_api_caida", ({"ds18b20":{"temperature":23.5}}, {"sht31":"disc"}, NetworkStatus("fail", 0))),
            ("14_alertas_multiples", ({"ds18b20":{"temperature":26.6},"sht31":{"temperature":25.4,"humidity":78}}, {}, NetworkStatus("ok"))),
        ]
        args.render_golden.mkdir(parents=True, exist_ok=True)
        for name, (readings, errors, network) in golden:
            history = {
                "temperature": [23.1 + .8 * math.sin(i / 11) for i in range(95)] + [
                    readings.get("sht31", {}).get("temperature")],
                "humidity": [88 + 5 * math.sin(i / 13) for i in range(95)] + [
                    readings.get("sht31", {}).get("humidity")],
                "substrate": [23 + 1.1 * math.sin(i / 12) for i in range(95)] + [
                    readings.get("ds18b20", {}).get("temperature")],
            }
            for page, suffix in ((0, "inicio"), (1, "resumen")):
                image = renderer.render(readings, errors, network, clock="17:28", now=180,
                                        page=page, history=history)
                image.save(args.render_golden / f"{name}__{suffix}.png")
        print(f"Rendered {len(golden) * 2} scenario images to {args.render_golden}")
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
