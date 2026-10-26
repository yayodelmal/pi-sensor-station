"""Render hardware-free single-page LCD previews."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from .colores import BACKGROUND, TEXT
from .monitor import MonitorConfig, NetworkStatus
from .render_v2 import Renderer


def scenarios():
    def values(temperature=23, humidity=88, substrate=23):
        return {"ds18b20": {"temperature": substrate},
                "sht31": {"temperature": temperature, "humidity": humidity}}

    return {
        "optimal": (values(), {}, NetworkStatus("ok")),
        "temperature-high": (values(25.4), {}, NetworkStatus("ok")),
        "temperature-low": (values(20.6), {}, NetworkStatus("ok")),
        "humidity-high": (values(humidity=96), {}, NetworkStatus("ok")),
        "humidity-low": (values(humidity=78), {}, NetworkStatus("ok")),
        "substrate-high": (values(substrate=26.6), {}, NetworkStatus("ok")),
        "substrate-low": (values(substrate=19.4), {}, NetworkStatus("ok")),
        "ds18b20-disconnected": ({"sht31": values()["sht31"]}, {"ds18b20": "disc"}, NetworkStatus("ok")),
        "sht31-disconnected": ({"ds18b20": values()["ds18b20"]}, {"sht31": "disc"}, NetworkStatus("ok")),
        "all-disconnected": ({}, {"ds18b20": "disc", "sht31": "disc"}, NetworkStatus("ok")),
        "sht31-no-data": ({"ds18b20": values()["ds18b20"]}, {"sht31": "nodata"}, NetworkStatus("ok")),
        "ds18b20-no-data": ({"sht31": values()["sht31"]}, {"ds18b20": "nodata"}, NetworkStatus("ok")),
        "api-failure": (values(), {}, NetworkStatus("fail", 0)),
        "http-disabled": (values(), {}, NetworkStatus("disabled")),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("previews"))
    parser.add_argument("--config", help="Monitor JSON configuration")
    parser.add_argument("--render-golden", type=Path, help="Write 15 single-page scenario PNGs")
    args = parser.parse_args()
    renderer = Renderer(MonitorConfig.load(args.config))
    examples = scenarios()

    if args.render_golden:
        golden = [
            ("00_optimo", examples["optimal"]),
            ("01_temp_alta", examples["temperature-high"]),
            ("02_temp_baja", examples["temperature-low"]),
            ("03_hum_alta", examples["humidity-high"]),
            ("04_hum_baja", examples["humidity-low"]),
            ("05_sustrato_alto", examples["substrate-high"]),
            ("06_sustrato_bajo", examples["substrate-low"]),
            ("07_ds18b20_desc", examples["ds18b20-disconnected"]),
            ("08_sht31_desc", examples["sht31-disconnected"]),
            ("09_ambos_desc", examples["all-disconnected"]),
            ("10_sht31_sin_lectura", examples["sht31-no-data"]),
            ("11_ds18b20_sin_lectura", examples["ds18b20-no-data"]),
            ("12_api_caida", examples["api-failure"]),
            ("13_alertas_multiples", (values_for_alerts(), {}, NetworkStatus("ok"))),
            ("14_http_desactivado", examples["http-disabled"]),
        ]
        args.render_golden.mkdir(parents=True, exist_ok=True)
        for name, (readings, errors, network) in golden:
            image = renderer.render(readings, errors, network, clock="17:28", now=180)
            image.save(args.render_golden / f"{name}__inicio.png")
        print(f"Rendered {len(golden)} single-page scenarios to {args.render_golden}")
        return

    args.output.mkdir(parents=True, exist_ok=True)
    columns = 2
    rows = (len(examples) + columns - 1) // columns
    sheet = Image.new("RGB", (480 * columns, 348 * rows), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    for i, (name, (readings, errors, network)) in enumerate(examples.items()):
        image = renderer.render(readings, errors, network, clock="17:28", now=180)
        image.save(args.output / (name + ".png"))
        x, y = (i % columns) * 480, (i // columns) * 348
        sheet.paste(image, (x, y))
        draw.text((x + 8, y + 325), name, fill=TEXT)
    sheet.save(args.output / "scenarios.png")
    print(f"Rendered {len(examples)} scenarios to {args.output}")


def values_for_alerts():
    return {"ds18b20": {"temperature": 26.6},
            "sht31": {"temperature": 25.4, "humidity": 78}}


if __name__ == "__main__":
    main()
