"""Display configuration and state, independent of framebuffer hardware."""

import errno
import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger("pi-sensor-station")


@dataclass(frozen=True)
class Range:
    minimum: float
    maximum: float
    scale_min: float
    scale_max: float

    def __post_init__(self):
        values = (self.scale_min, self.minimum, self.maximum, self.scale_max)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError("Monitor ranges must contain finite numbers")
        if not self.scale_min <= self.minimum < self.maximum <= self.scale_max:
            raise ValueError("Expected scale_min <= minimum < maximum <= scale_max")


@dataclass(frozen=True)
class MonitorConfig:
    temperature: Range = field(default_factory=lambda: Range(22, 24, 16, 32))
    humidity: Range = field(default_factory=lambda: Range(85, 92, 60, 100))
    temperature_source: str = "ds18b20"
    temperature_fallback: bool = True

    def __post_init__(self):
        if self.temperature_source not in ("ds18b20", "sht31"):
            raise ValueError("temperature_source must be ds18b20 or sht31")
        if not isinstance(self.temperature_fallback, bool):
            raise ValueError("temperature_fallback must be true or false")
        if not 0 <= self.humidity.scale_min < self.humidity.scale_max <= 100:
            raise ValueError("Humidity scale must be within 0..100")

    @classmethod
    def load(cls, filename=None):
        if not filename:
            return cls()
        try:
            data = json.loads(Path(filename).read_text())
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            for key in ("temperature", "humidity"):
                if key in data:
                    data[key] = Range(**data[key])
            return cls(**data)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            LOG.warning("Invalid monitor configuration; using defaults: %s", error)
            return cls()


def error_status(error):
    # An invalid CRC is not evidence that the sensor is physically absent.
    from .sensors import SensorDisconnected

    if isinstance(error, SensorDisconnected):
        return "disc"
    if isinstance(error, OSError) and error.errno in (errno.ENOENT, errno.ENXIO, errno.ENODEV, errno.EREMOTEIO):
        return "disc"
    return "nodata"


@dataclass(frozen=True)
class Panel:
    state: str
    value: object
    tag: str
    note: str
    fallback: bool = False


def decimal(value):
    return f"{value:.1f}".replace(".", ",")


def valid_value(readings, errors, sensor, key):
    if sensor in errors:
        return None
    value = readings.get(sensor, {}).get(key)
    low, high = (0, 100) if key == "humidity" else ((-55, 125) if sensor == "ds18b20" else (-40, 125))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        return None
    return value


def measured_panel(value, limits, tag, temperature, fallback=False):
    state = "low" if value < limits.minimum else "high" if value > limits.maximum else "ok"
    if state == "ok":
        note = "Dentro del objetivo"
    else:
        distance = limits.minimum - value if state == "low" else value - limits.maximum
        amount = decimal(distance) if temperature else str(math.floor(distance + 0.5))
        note = ("−" if state == "low" else "+") + amount + (" bajo el mínimo" if state == "low" else " sobre el máximo")
    return Panel(state, value, tag, note, fallback)


def resolve_panels(readings, errors, config):
    source = config.temperature_source
    other = "sht31" if source == "ds18b20" else "ds18b20"
    candidates = (source, other) if config.temperature_fallback else (source,)
    temperature = None
    for sensor in candidates:
        value = valid_value(readings, errors, sensor, "temperature")
        if value is not None:
            fallback = sensor != source
            temperature = measured_panel(value, config.temperature, sensor.upper() + (" · respaldo" if fallback else ""), True, fallback)
            break
    if temperature is None:
        disconnected = all(errors.get(sensor) == "disc" for sensor in candidates)
        temperature = Panel("disc" if disconnected else "nodata", None,
                            " · ".join(sensor.upper() for sensor in candidates),
                            "Sin sensores conectados" if disconnected else "Sin lectura válida")
    humidity = valid_value(readings, errors, "sht31", "humidity")
    if humidity is not None:
        humidity = measured_panel(humidity, config.humidity, "SHT31", False)
    else:
        disconnected = errors.get("sht31") == "disc"
        humidity = Panel("disc" if disconnected else "nodata", None, "SHT31",
                         "SHT31 desconectado" if disconnected else "Sin lectura válida")
    return temperature, humidity


@dataclass
class NetworkStatus:
    state: str = "waiting"
    failed_since: object = None
    last_success: object = None

    def update(self, results, now=None):
        now = time.monotonic() if now is None else now
        if results and all(value == "ok" for value in results.values()):
            self.state, self.failed_since, self.last_success = "ok", None, now
        else:
            self.state = "fail"
            if self.failed_since is None:
                self.failed_since = now

    def label(self, now=None):
        if self.state == "fail":
            now = time.monotonic() if now is None else now
            elapsed = max(0, now - (self.failed_since if self.failed_since is not None else now))
            duration = "<1 min" if elapsed < 60 else f"{min(999, int(elapsed // 60))} min"
            return f"API sin conexión · {duration}"
        return {"disabled": "HTTP desactivado", "waiting": "API pendiente", "ok": ""}[self.state]
