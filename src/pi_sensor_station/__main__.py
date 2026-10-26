import argparse
import logging
import math
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .api import API
from .sensors import DS18B20, SHT31
from .monitor import MonitorConfig, NetworkStatus, error_status
from .notify import ready as notify_ready
from .history import History

LOG = logging.getLogger("pi-sensor-station")


def positive_env(name, default):
    value = float(os.getenv(name, default))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def main():
    parser = argparse.ArgumentParser(description="Read sensors, update the LCD and send readings over HTTP")
    parser.add_argument("--simulate", action="store_true", help="Use fixed example readings")
    parser.add_argument("--no-send", action="store_true", help="Disable HTTP requests")
    parser.add_argument("--no-display", action="store_true", help="Disable framebuffer access")
    parser.add_argument("--once", action="store_true", help="Read once, await any HTTP send, then exit")
    parser.add_argument("--page", choices=("home", "summary"), default="home", help="Initial display page")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        read_interval = positive_env("READ_INTERVAL", "5")
        send_interval = positive_env("SEND_INTERVAL", "30")
        timeout = positive_env("HTTP_TIMEOUT", "5")
        config = MonitorConfig.load(os.getenv("MONITOR_CONFIG"))
        api = None if args.no_send else API(os.environ.get("API_URL", ""), os.getenv("API_TOKEN", ""), timeout)
        sensors = {} if args.simulate else {
            "sht31": SHT31(int(os.getenv("I2C_BUS", "1")), int(os.getenv("SHT31_ADDRESS", "0x44"), 0)),
            "ds18b20": DS18B20(os.getenv("DS18B20_ID", "")),
        }
    except (ValueError, OSError) as error:
        parser.error(str(error))

    display = None
    if not args.no_display:
        try:
            from .display import Display

            display = Display(os.getenv("FRAMEBUFFER", "/dev/fb1"), config)
        except (OSError, ValueError, ImportError) as error:
            LOG.warning("LCD unavailable; continuing without display: %s", error)

    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    network = NetworkStatus("disabled" if api is None else "waiting")
    history = History(os.getenv("HISTORY_PATH", "/home/zero/.local/state/pi-sensor-station/history.json"))
    try:
        from .touch import TouchReader
        touch = TouchReader(os.getenv("TOUCH_DEVICE"),
                            tuple(map(int, os.getenv("TOUCH_RAW_X", "0,4095").split(","))),
                            tuple(map(int, os.getenv("TOUCH_RAW_Y", "0,4095").split(","))),
                            int(os.getenv("TOUCH_ROTATION", "0")))
    except (OSError, ValueError) as error:
        LOG.info("Touch input unavailable: %s", error)
        touch = None
    page = 1 if args.page == "summary" else 0
    if args.simulate:
        LOG.warning("SIMULATION: readings are examples%s", "; HTTP sending is enabled" if api else "")
    next_send = 0
    next_read = 0
    pending = None
    notified = False
    readings, errors = {}, {}
    with ThreadPoolExecutor(max_workers=1) as executor:
        while not stop.is_set():
            started = time.monotonic()
            if pending is not None and pending.done():
                results = pending.result()
                LOG.info("HTTP results: %s", results)
                network.update(results)
                pending = None
            if started >= next_read:
                readings, errors = {}, {}
                if args.simulate:
                    readings = {"sht31": {"temperature": 23.2, "humidity": 88.0}, "ds18b20": {"temperature": 23.0}}
                else:
                    for name, sensor in sensors.items():
                        try:
                            readings[name] = sensor.read()
                        except Exception as error:
                            errors[name] = error_status(error)
                            LOG.warning("%s read failed: %s", name, error)
                LOG.info("%sreadings: %s", "SIMULATED " if args.simulate else "", readings)
                history.update(resolve_history_values(readings, errors, config))
                next_read = time.monotonic() + read_interval
            if api and readings and pending is None and time.monotonic() >= next_send:
                pending = executor.submit(api.send, readings)
                next_send = time.monotonic() + send_interval
            if display:
                try:
                    if touch:
                        for direction in touch.poll(): page = max(0, min(1, page + direction))
                    display.draw(readings, errors, network, simulated=args.simulate, page=page,
                                 history=history.samples)
                except (OSError, ValueError) as error:
                    LOG.warning("LCD update failed: %s", error)
            if args.once:
                if pending:
                    results = pending.result()
                    LOG.info("HTTP results: %s", results)
                    network.update(results)
                    if display:
                        try:
                            display.draw(readings, errors, network, simulated=args.simulate)
                        except (OSError, ValueError) as error:
                            LOG.warning("LCD update failed: %s", error)
                    if any(v != "ok" for v in results.values()):
                        return 1
                return 1 if errors else 0
            if not notified:
                notify_ready()
                notified = True
            # Poll completion and update the clock without reading sensors at 1 Hz.
            delay = min(1, max(0, next_read - time.monotonic()))
            history.flush_if_due(float(os.getenv("HISTORY_FLUSH_S", "60")))
            stop.wait(delay)
    history.flush_if_due(force=True)
    if touch:
        touch.close()
    return 0


def resolve_history_values(readings, errors, config):
    """Return valid effective temperature and humidity for the current interval."""
    from .monitor import valid_value
    source = config.temperature_source
    other = "sht31" if source == "ds18b20" else "ds18b20"
    temp = valid_value(readings, errors, source, "temperature")
    if temp is None and config.temperature_fallback:
        temp = valid_value(readings, errors, other, "temperature")
    humidity = valid_value(readings, errors, "sht31", "humidity")
    return {"temperature": temp, "humidity": humidity}


if __name__ == "__main__":
    raise SystemExit(main())
