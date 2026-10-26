"""Optional systemd readiness notification; no dependency on python-systemd."""

import os
import socket


def ready():
    address = os.getenv("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
        connection.connect(address)
        connection.sendall(b"READY=1\nSTATUS=Sensor station initialized")
