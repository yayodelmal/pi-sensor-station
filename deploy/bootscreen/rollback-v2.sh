#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

backup=/opt/bootscreen.bak-20261025
for path in bootscreen/config.py bootscreen/render.py bootscreen/framebuffer.py \
            bootscreen/state.py bootscreen/__main__.py bootscreen/probes.py \
            etc/bootscreen/config.toml etc/systemd/system/bootscreen.service \
            usr/local/bin/bootscreen; do
    test -f "$backup/tree/$path" || test -f "$backup/$path"
done

if [ "${1:-}" = "--check" ]; then
    echo "Rollback sources are present for all v2-modified files."
    exit 0
fi

systemctl stop bootscreen.service || true
cp -a "$backup/tree/." /opt/bootscreen/
cp -a "$backup/etc/bootscreen/config.toml" /etc/bootscreen/config.toml
cp -a "$backup/etc/systemd/system/bootscreen.service" /etc/systemd/system/bootscreen.service
cp -a "$backup/usr/local/bin/bootscreen" /usr/local/bin/bootscreen
systemctl daemon-reload
systemctl start bootscreen.service
echo "Restored the 2026-10-25 bootscreen; the Raspberry Pi was not rebooted."
