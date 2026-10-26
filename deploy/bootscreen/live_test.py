#!/usr/bin/env python3
"""Exercise countdown/recovery on the LCD without changing Wi-Fi, SSH or real config."""

import json
import os
import subprocess
import time
from pathlib import Path


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo")
    active = subprocess.run(["systemctl", "is-active", "--quiet", "bootscreen.service"], check=False)
    if active.returncode == 0:
        raise SystemExit("Run this test before starting bootscreen.service; it will not stop the real service")
    directory = Path("/run/bootscreen/selftest")
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "network-ready"
    marker.unlink(missing_ok=True)
    config = directory / "config.toml"
    text = Path("/etc/bootscreen/config.toml").read_text()
    text = text.replace('kind = "network"', 'kind = "command"\ncommand = ["/usr/bin/test", "-f", "' + str(marker) + '"]')
    text = text.replace("timeout = 60", "timeout = 2")
    config.write_text(text)
    status = Path("/run/bootscreen/status.json")
    status.unlink(missing_ok=True)
    process = subprocess.Popen(["/usr/local/bin/bootscreen", "--config", str(config)])
    countdown, recovering, ready = [], False, False
    started = time.monotonic()
    try:
        while time.monotonic() - started < 35:
            if process.poll() is not None:
                raise RuntimeError("Bootscreen exited during the test")
            try:
                current = json.loads(status.read_text())
            except (OSError, ValueError):
                time.sleep(0.1)
                continue
            if current["mode"] == "error":
                remaining = current["retry_in"]
                if remaining not in countdown:
                    countdown.append(remaining)
                    print("countdown", remaining, flush=True)
                if remaining <= 5 and not recovering:
                    marker.touch()
                    recovering = True
                    print("Simulated check recovered; actual wlan0 was not changed", flush=True)
            if recovering and current["mode"] == "ready":
                ready = True
                break
            time.sleep(0.1)
        assert countdown and countdown[0] == 8 and 0 in countdown and ready, (countdown, ready)
        print(json.dumps({"countdown": countdown, "recovered_to_ready": ready, "network_modified": False}), flush=True)
    finally:
        process.terminate()
        process.wait(timeout=5)
        marker.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
