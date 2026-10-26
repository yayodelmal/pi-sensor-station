#!/usr/bin/env python3
"""Install the reviewed bootscreen without pip or changing network/SSH configuration."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def quiet_cmdline(text):
    desired = {"quiet", "logo.nologo", "loglevel=3", "vt.global_cursor_default=0", "consoleblank=0", "fbcon=map:0"}
    keys = {part.split("=", 1)[0] for part in desired}
    parts = [part for part in text.split() if part != "splash" and part.split("=", 1)[0] not in keys]
    return " ".join(parts + sorted(desired)) + "\n"


def unit_state(unit, verb):
    result = subprocess.run(["systemctl", verb, unit], capture_output=True, text=True, check=False)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-demo-app", action="store_true", required=True,
                        help="Explicitly install the authorized headless, no-HTTP demo service")
    parser.add_argument("--station-user", default="zero")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", args.station_user):
        parser.error("Invalid station user")
    import PIL  # Verify the system package before changing anything.
    import tomllib

    config_path = Path("/boot/firmware/config.txt")
    if not config_path.exists():
        config_path = Path("/boot/config.txt")
    cmdline_path = config_path.with_name("cmdline.txt")
    assert config_path.is_file() and cmdline_path.is_file(), "Boot configuration files not found"
    with (HERE / "config.toml").open("rb") as handle:
        tomllib.load(handle)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path("/var/lib/bootscreen/backups") / stamp
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup, 0o700)
    changes = {}
    for source in (REPO / "src/bootscreen").rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
            changes[Path("/opt/bootscreen/bootscreen") / source.relative_to(REPO / "src/bootscreen")] = (source.read_bytes(), 0o644)
    for source in (REPO / "src/pi_sensor_station").glob("*.py"):
        changes[Path("/opt/bootscreen/station/pi_sensor_station") / source.name] = (source.read_bytes(), 0o644)
    launcher = "#!/bin/sh\nexport PYTHONPATH=/opt/bootscreen\nexec /usr/bin/python3 -m bootscreen \"$@\"\n"
    changes[Path("/usr/local/bin/bootscreen")] = (launcher.encode(), 0o755)
    changes[Path("/etc/bootscreen/config.toml")] = ((HERE / "config.toml").read_bytes(), 0o644)
    changes[Path("/etc/systemd/system/bootscreen.service")] = ((HERE / "bootscreen.service").read_bytes(), 0o644)
    app = (HERE / "pi-sensor-station-demo.service").read_text().replace("User=zero", "User=" + args.station_user)
    changes[Path("/etc/systemd/system/pi-sensor-station.service")] = (app.encode(), 0o644)
    config = config_path.read_text()
    if "# bootscreen: firmware splash" not in config:
        config += "\n[all]\n# bootscreen: firmware splash\ndisable_splash=1\n"
    changes[config_path] = (config.encode(), config_path.stat().st_mode & 0o777)
    changes[cmdline_path] = (quiet_cmdline(cmdline_path.read_text()).encode(), cmdline_path.stat().st_mode & 0o777)
    rollback_launcher = f"#!/bin/sh\nexec /usr/bin/python3 '{backup}/rollback.py' \"$@\"\n"
    changes[Path("/usr/local/sbin/bootscreen-rollback")] = (rollback_launcher.encode(), 0o755)
    manifest = {"units": {u: {"enabled": unit_state(u, "is-enabled"), "active": unit_state(u, "is-active")}
                           for u in ("bootscreen.service", "pi-sensor-station.service")}, "files": []}
    # Freeze backups and rollback before the first modification of managed paths.
    for i, (path, (data, mode)) in enumerate(changes.items()):
        saved = None
        if path.exists():
            saved = str(backup / f"file-{i}")
            shutil.copy2(path, saved)
            if path in (config_path, cmdline_path) or path.suffix == ".service":
                dated = path.with_name(path.name + ".bak-" + stamp)
                shutil.copy2(path, dated)
        manifest["files"].append({"path": str(path), "backup": saved,
                                  "installed_sha256": hashlib.sha256(data).hexdigest(), "mode": mode})
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2))
    shutil.copy2(HERE / "rollback.py", backup / "rollback.py")
    (backup / "rollback.sh").write_text(rollback_launcher)
    (backup / "rollback.sh").chmod(0o700)
    print("Rollback prepared:", backup / "rollback.sh", flush=True)
    for path, (data, mode) in changes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemd-analyze", "verify", "/etc/systemd/system/bootscreen.service",
                    "/etc/systemd/system/pi-sensor-station.service"], check=True)
    # Enable only; the caller starts live tests after checking display ownership.
    subprocess.run(["systemctl", "enable", "bootscreen.service", "pi-sensor-station.service"], check=True)
    print("Installed and enabled. No reboot or network changes performed.")


if __name__ == "__main__":
    main()
