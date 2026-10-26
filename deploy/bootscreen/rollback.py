#!/usr/bin/env python3
"""Restore only files managed by the corresponding bootscreen installation."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def run(*args):
    subprocess.run(args, check=False)


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo")
    manifest = json.loads(Path(__file__).with_name("manifest.json").read_text())
    for unit in manifest["units"]:
        run("systemctl", "disable", "--now", unit)
    for item in reversed(manifest["files"]):
        path = Path(item["path"])
        if item["backup"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item["backup"], path)
        elif path.is_file():
            if hashlib.sha256(path.read_bytes()).hexdigest() == item["installed_sha256"]:
                path.unlink()
            else:
                print("Preserving file changed since installation:", path)
    run("systemctl", "daemon-reload")
    for unit, state in manifest["units"].items():
        if state["enabled"] == "enabled":
            run("systemctl", "enable", unit)
        if state["active"] == "active":
            run("systemctl", "start", unit)
    print("Original files restored. Backups retained. Reboot when convenient to apply boot options.")


if __name__ == "__main__":
    main()
