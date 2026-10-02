"""Other computers on the network: the addresses they use to open SMP, and whether a request came from this one.

SMP listens on every network interface (unless the "lan" setting is off), so a browser on another PC in the studio
opens it at http://<this computer's address>:<port>/. Windows only lets that through with the firewall rule the
installer adds (FIREWALL_RULE)."""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
from functools import lru_cache

FIREWALL_RULE = "IVAR SMP"      # the same name as in installer/install.ps1


def lan_addresses() -> list[str]:
    """This computer's IPv4 addresses on its networks, the one with the default route first."""
    found: list[str] = []
    try:                        # the address the default route leaves from (a UDP "connect" sends nothing)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += [a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    out = []
    for a in found:
        ip = ipaddress.ip_address(a)
        if not (ip.is_loopback or ip.is_link_local or ip.is_unspecified) and a not in out:
            out.append(a)
    return out


def is_this_computer(host: str | None) -> bool:
    """The request came from a browser on the computer SMP runs on (so its folder dialog shows up in front of them)."""
    if not host:
        return False
    try:
        if ipaddress.ip_address(host).is_loopback:
            return True
    except ValueError:
        return host == "localhost"
    return host in lan_addresses()


@lru_cache(maxsize=1)
def firewall_rule() -> bool | None:
    """Windows: the installer's firewall rule exists. None elsewhere (no firewall SMP knows how to check)."""
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE}"],
                           capture_output=True, creationflags=0x08000000, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None
