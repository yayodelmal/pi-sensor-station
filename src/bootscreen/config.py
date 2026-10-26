import math
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib


@dataclass(frozen=True)
class Check:
    label: str
    kind: str
    units: tuple = ()
    enabled: bool = True
    timeout: float = 60
    error_title: str = "ERROR"
    command: tuple = ()
    host: str = "127.0.0.1"
    port: int = 0

    def __post_init__(self):
        if self.kind not in ("systemd", "network", "command", "tcp"):
            raise ValueError("Unknown check kind")
        if not self.label or len(self.label) > 16:
            raise ValueError("Step labels must have 1..16 characters")
        if not 1 <= len(self.error_title) <= 10:
            raise ValueError("Error titles must have 1..10 characters")
        if not isinstance(self.enabled, bool) or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("Invalid step enabled/timeout")
        if self.kind == "systemd" and not self.units:
            raise ValueError("Systemd checks need at least one unit")
        if any(not re.fullmatch(r"[A-Za-z0-9_.@:-]+", unit) or unit.startswith("-") for unit in self.units):
            raise ValueError("Invalid systemd unit name")
        if self.kind == "command" and (not self.command or any(not isinstance(v, str) for v in self.command)):
            raise ValueError("Command checks need an argv array")
        if self.kind == "tcp" and not 1 <= self.port <= 65535:
            raise ValueError("TCP check port must be 1..65535")


@dataclass(frozen=True)
class AnimationConfig:
    enabled: bool = True
    blink: bool = True
    dots: bool = True
    step_flash: bool = True
    ready_intro: bool = True
    error_strip: bool = True
    max_fps: int = 5

    def __post_init__(self):
        if any(not isinstance(getattr(self, name), bool) for name in
               ("enabled", "blink", "dots", "step_flash", "ready_intro", "error_strip")):
            raise ValueError("Animation switches must be boolean")
        if not isinstance(self.max_fps, int) or not 1 <= self.max_fps <= 30:
            raise ValueError("animations.max_fps must be in 1..30")


def default_steps():
    return (
        Check("Sistema", "systemd", ("basic.target",)),
        Check("Wi-Fi", "network", error_title="SIN WI-FI"),
        Check("Servicios", "systemd", ("ssh.service", "avahi-daemon.service")),
        Check("App", "systemd", ("pi-sensor-station.service",)),
    )


@dataclass(frozen=True)
class Config:
    framebuffer: str = "/dev/fb1"
    interface: str = "wlan0"
    blink: bool = False
    retry_seconds: int = 8
    poll_seconds: float = 1
    check_timeout: float = 1
    steps: tuple = field(default_factory=default_steps)
    animations: AnimationConfig = field(default_factory=AnimationConfig)

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", self.interface) or self.interface.startswith("-"):
            raise ValueError("Invalid network interface")
        if not re.fullmatch(r"/dev/fb[0-9]+", self.framebuffer):
            raise ValueError("framebuffer must name /dev/fbN")
        if not isinstance(self.blink, bool) or not isinstance(self.retry_seconds, int) or not 1 <= self.retry_seconds <= 99:
            raise ValueError("Invalid blink/retry_seconds")
        for v in (self.poll_seconds, self.check_timeout):
            if not math.isfinite(v) or not 0.1 <= v <= 10:
                raise ValueError("Polling and check timeout must be in 0.1..10 seconds")
        if len(self.steps) != 4 or len({step.label for step in self.steps}) != 4:
            raise ValueError("Expected four uniquely named steps")

    @classmethod
    def load(cls, path):
        with Path(path).open("rb") as handle:
            data = tomllib.load(handle)
        values = dict(data.get("display", {}))
        values.update(data.get("runtime", {}))
        unknown = set(data) - {"display", "runtime", "steps", "animations"}
        if unknown:
            raise ValueError(f"Unknown TOML sections: {sorted(unknown)}")
        if "steps" in data:
            steps = []
            for raw in data["steps"]:
                raw = dict(raw)
                for key in ("units", "command"):
                    if key in raw:
                        if not isinstance(raw[key], list) or any(not isinstance(v, str) for v in raw[key]):
                            raise ValueError(f"{key} must be an array of strings")
                        raw[key] = tuple(raw[key])
                steps.append(Check(**raw))
            values["steps"] = tuple(steps)
        if "animations" in data:
            values["animations"] = AnimationConfig(**data["animations"])
        try:
            return cls(**values)
        except TypeError as error:
            raise ValueError(str(error)) from error
