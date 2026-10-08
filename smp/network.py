"""Other computers on the network: the addresses they use to open SMP, and whether a request came from this one.

SMP listens on every network interface (unless the "lan" setting is off), so a browser on another PC in the studio
opens it at http://<this computer's address>:<port>/. Windows only lets that through with the firewall rule the
installer adds (FIREWALL_RULE).

There's no login, so two things keep other web pages out: a request must name this computer (is_own_name), since a
page can point a domain of its own at this computer's address (DNS rebinding), and the server refuses changes sent
from another site's page (see the Origin check in server.py)."""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import time
from functools import lru_cache

FIREWALL_RULE = "IVAR SMP"      # the same name as in installer/install.ps1
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_names: tuple[float, frozenset[str]] = (0.0, frozenset())


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


def own_names() -> frozenset[str]:
    """This computer's addresses and its name (also as name.local, for macOS), as a browser on the network uses them.
    Kept for 30 seconds: every request is checked against them, and looking up the computer's own name can be slow."""
    global _names
    at, names = _names
    if time.monotonic() - at > 30:
        host = socket.gethostname().lower()
        names = frozenset({*lan_addresses(), host, host + ".local"})
        _names = (time.monotonic(), names)
    return names


def is_own_name(name: str, lan: bool) -> bool:
    """A browser asked for SMP by one of this computer's names (only "localhost" and the like when lan is off)."""
    name = name.lower()
    return name in LOOPBACK_NAMES or (lan and name in own_names())


def is_this_computer(host: str | None) -> bool:
    """The request came from a browser on the computer SMP runs on: its folder dialog shows up in front of them, and
    only they can change the programs, models, Claude key and network settings."""
    if not host:
        return False
    try:
        if ipaddress.ip_address(host).is_loopback:
            return True
    except ValueError:
        return host == "localhost"
    return host in own_names()


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
