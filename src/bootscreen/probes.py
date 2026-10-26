import ipaddress
import json
import socket
import subprocess
from dataclasses import dataclass, field


@dataclass
class Snapshot:
    units: dict = field(default_factory=dict)
    network_ok: bool = False
    ip: str = ""
    other: dict = field(default_factory=dict)
    network_checked: bool = True

    def known(self, check):
        """Whether this snapshot contains a completed observation for a check."""
        if not check.enabled:
            return True
        if check.kind == "systemd":
            return all(unit in self.units for unit in check.units)
        if check.kind == "network":
            return self.network_checked
        return check.label in self.other

    def ready(self, check):
        if not check.enabled:
            return True
        if check.kind == "systemd":
            return all(self.units.get(unit, False) for unit in check.units)
        if check.kind == "network":
            return self.network_ok
        return self.other.get(check.label, False)


def network_address(addresses, routes, interface):
    # `ip route ... dev <interface>` may omit `dev` in its JSON result because
    # the query itself already restricted the route to that interface.
    if not any(route.get("dev") in (None, interface) and route.get("dst") == "default"
               and route.get("type", "unicast") == "unicast" for route in routes):
        return ""
    for entry in addresses:
        if entry.get("ifname") != interface:
            continue
        for value in entry.get("addr_info", []):
            if value.get("family") != "inet" or value.get("scope") != "global":
                continue
            ip = ipaddress.ip_address(value["local"])
            if ip.version == 4 and not ip.is_loopback and not ip.is_link_local:
                return str(ip)
    return ""


class Probes:
    def __init__(self, config):
        self.config = config

    def run(self, argv):
        try:
            return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, timeout=self.config.check_timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def sample(self):
        snapshot = Snapshot()
        units = sorted({unit for step in self.config.steps if step.enabled for unit in step.units})
        if units:
            result = self.run(["systemctl", "--no-pager", "is-active", "--", *units])
            if result:
                snapshot.units = {unit: value == "active" for unit, value in zip(units, result.stdout.splitlines())}
        if any(s.enabled and s.kind == "network" for s in self.config.steps):
            snapshot.network_checked = False
            addresses = self.run(["ip", "-j", "-4", "address", "show", "dev", self.config.interface])
            routes = self.run(["ip", "-j", "-4", "route", "show", "default", "dev", self.config.interface])
            if addresses is not None and routes is not None:
                snapshot.network_checked = True
            if addresses and routes and addresses.returncode == routes.returncode == 0:
                try:
                    snapshot.ip = network_address(json.loads(addresses.stdout), json.loads(routes.stdout), self.config.interface)
                    snapshot.network_ok = bool(snapshot.ip)
                except (ValueError, TypeError, KeyError):
                    snapshot.network_checked = False
        for step in self.config.steps:
            if not step.enabled:
                continue
            if step.kind == "command":
                result = self.run(list(step.command))
                if result is not None:
                    snapshot.other[step.label] = result.returncode == 0
            elif step.kind == "tcp":
                try:
                    with socket.create_connection((step.host, step.port), timeout=self.config.check_timeout):
                        snapshot.other[step.label] = True
                except OSError:
                    snapshot.other[step.label] = False
        return snapshot
