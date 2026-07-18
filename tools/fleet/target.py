"""Shared SSH-target transport helpers.

Used by `infect` and `install` to normalise `user@host:port` addresses and
execute scripts / upload files over SSH.
"""

import base64
import shlex
import subprocess
import sys
import time
from pathlib import Path

from common import die
from known_hosts import clear_local_known_host

SSH_RETRIES = 3


def normalize_ssh_target(value, default_port=22, default_user="root"):
    """Parse ``user@host:port`` into (user, host, port, raw_port).

    If *default_port* is set and the target does not include ``:port``, the
    default is used.  *raw_port* is the original port string (for error
    messages or special handling).
    """
    user = default_user
    host = value
    port = default_port
    raw_port = None

    if ":" in value.rsplit("@", 1)[-1]:
        # last segment contains a colon → port
        idx = value.rfind(":")
        port_str = value[idx + 1:]
        host = value[:idx]
        try:
            port = int(port_str)
        except ValueError:
            die(f"invalid port in ssh target: {port_str}")
        raw_port = port_str

    if "@" in host:
        user, host = host.split("@", 1)
        if not user or not host:
            die(f"invalid ssh target: {value}")

    return user, host, port, raw_port


def ssh_base(user, host, port, *, timeout=30):
    """Return the base SSH command-line for ``user@host:port``."""
    clear_local_known_host(host, port)
    ssh_bin = "/usr/bin/ssh" if Path("/usr/bin/ssh").exists() else "ssh"
    return [
        ssh_bin,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={int(timeout)}",
        "-o", "ConnectionAttempts=1",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=4",
        "-p", str(port),
        f"{user}@{host}",
    ]


def _ssh_retry_delay(attempt):
    return min(2 ** attempt, 10)


def _should_retry_ssh(exc):
    return isinstance(exc, subprocess.CalledProcessError) and exc.returncode == 255


def target_run(user, host, port, script, *, timeout=30, input_text=None, capture_output=False, retries=SSH_RETRIES):
    """Execute *script* on the target via SSH."""
    argv = [*ssh_base(user, host, port, timeout=timeout), "set -eu; " + script]
    printable = " ".join(shlex.quote(str(a)) for a in argv)
    print(f"+ {printable}", file=sys.stderr)
    for attempt in range(retries + 1):
        try:
            if capture_output:
                return subprocess.check_output(argv, input=input_text, text=True)
            subprocess.run(argv, input=input_text, text=True, check=True)
            return ""
        except subprocess.CalledProcessError as exc:
            if not _should_retry_ssh(exc) or attempt >= retries:
                raise
            delay = _ssh_retry_delay(attempt)
            print(f"[fleet] SSH failed with 255; retry {attempt + 1}/{retries} in {delay}s", file=sys.stderr)
            time.sleep(delay)
    return ""


def target_upload_text(user, host, port, path, text, *, mode="0644", timeout=30):
    """Upload *text* (base64-encoded) to *path* on the target."""
    encoded = base64.b64encode(text.encode()).decode()
    script = (
        f"install -d -m 0755 {shlex.quote(str(Path(path).parent))}; "
        f"base64 -d > {shlex.quote(path)}; "
        f"chmod {shlex.quote(mode)} {shlex.quote(path)}"
    )
    target_run(user, host, port, script, timeout=timeout, input_text=encoded)


def target_read_text(user, host, port, path, *, timeout=30):
    """Read *path* contents from the target."""
    return target_run(user, host, port, f"cat {shlex.quote(path)}", timeout=timeout, capture_output=True)


# ---------------------------------------------------------------------------
# SSH availability helpers (reboot / reconnect)
# ---------------------------------------------------------------------------


def ssh_probe(user, host, port, *, timeout=8):
    """Return ``True`` if an SSH connection to the target succeeds."""
    result = subprocess.run(
        [*ssh_base(user, host, port, timeout=timeout), "true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def wait_ssh_down(user, host, port, *, timeout=120, poll_interval=3):
    """Wait until SSH on *port* is **unreachable** (e.g. after ``reboot``).

    Useful after issuing a reboot command: the old SSH session should drop,
    and we wait until the target stops responding before polling for it to
    come back up.  If the host is already down, returns immediately.
    """
    deadline = time.time() + int(timeout)
    while time.time() < deadline:
        if not ssh_probe(user, host, port, timeout=5):
            return
        time.sleep(poll_interval)


def wait_ssh_up(user, host, port, *, timeout=600, poll_interval=5):
    """Wait until SSH on *port* is reachable and responds.

    After a reboot, call :func:`wait_ssh_down` first, then this function.
    """
    deadline = time.time() + int(timeout)
    while time.time() < deadline:
        if ssh_probe(user, host, port, timeout=8):
            return
        time.sleep(poll_interval)
    die(f"timed out waiting for SSH on {user}@{host}:{port}")


def wait_ssh_reboot(user, host, port, *, down_timeout=120, up_timeout=600):
    """Full reboot wait: wait for SSH to go down, then come back up."""
    wait_ssh_down(user, host, port, timeout=down_timeout)
    clear_local_known_host(host, port, force=True)
    wait_ssh_up(user, host, port, timeout=up_timeout)


def _demo():
    assert _should_retry_ssh(subprocess.CalledProcessError(255, ["ssh"]))
    assert not _should_retry_ssh(subprocess.CalledProcessError(1, ["ssh"]))
    assert [_ssh_retry_delay(i) for i in range(4)] == [1, 2, 4, 8]


if __name__ == "__main__":
    _demo()
