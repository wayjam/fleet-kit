"""Known-hosts maintenance for fleet-managed SSH endpoints."""

from __future__ import annotations

import subprocess
from pathlib import Path


_CLEARED_LOCAL_KEYS: set[tuple[str, int | None, str]] = set()


def known_host_names(host: str, port: int | None = None) -> list[str]:
    """Return known_hosts lookup names for *host* and optional *port*."""
    host = str(host).strip()
    if not host:
        return []
    names = []
    if port is not None:
        names.append(f"[{host}]:{int(port)}")
    names.append(host)
    return list(dict.fromkeys(names))


def clear_local_known_host(host: str, port: int | None = None, *, force: bool = False) -> None:
    """Remove stale local known_hosts entries so accept-new can trust the next key."""
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if not known_hosts.exists():
        return
    key = (str(host), int(port) if port is not None else None, str(known_hosts))
    if not force and key in _CLEARED_LOCAL_KEYS:
        return
    for name in known_host_names(host, port):
        subprocess.run(
            ["ssh-keygen", "-R", name, "-f", str(known_hosts)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    _CLEARED_LOCAL_KEYS.add(key)


def remote_clear_known_host_script(host: str, port: int | None = None, *, path: str = "/root/.ssh/known_hosts") -> str:
    """Return shell code that removes stale known_hosts entries on a remote machine."""
    import shlex

    commands = [
        f"ssh-keygen -R {shlex.quote(name)} -f {shlex.quote(path)} >/dev/null 2>&1 || true"
        for name in known_host_names(host, port)
    ]
    return "; ".join(commands)
