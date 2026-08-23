"""Shared helpers: config loading, subprocess wrappers, small utilities."""

import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    print("error: Python 3.11+ is required for tomllib", file=sys.stderr)
    sys.exit(127)


DEFAULT_CONFIG = {
    "paths": {
        "ssh_config": "local/ssh-config",
        "remote_root": "/root",
        "secret_key_dir": "local/keys",
        "node_age_key": "local/node-age.txt",
    },
    "builder": {
        "default": "",
        "ssh_key": "-",
        "memory": 768,
        "use_kvm": True,
        "remote_nix": "auto",
        # auto | rsync | tar — auto uses rsync when both ends have it
        "sync_method": "auto",
    },
    "builders": {},
    "repos": {
        "public_name": "fleet-kit",
        "inventory_name": "fleet-inventory",
        # flake input attribute for the public kit (not the directory name)
        "fleetkit_input": "fleetkit",
        # auto | path | remote — path syncs sibling kit; remote lets builder fetch
        "fleetkit_mode": "auto",
    },
}


def deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_toml(path):
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def repo_root():
    return Path.cwd()


def load_config():
    root = repo_root()
    config = DEFAULT_CONFIG
    config = deep_merge(config, load_toml(root / "fleet.toml"))
    config = deep_merge(config, load_toml(root / "local" / "fleet.toml"))
    return config


def repo_path(value):
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return repo_root() / path


def remote_repo_path(config, value, builder):
    path = Path(value).expanduser()
    if path.is_absolute():
        try:
            rel = path.relative_to(repo_root())
        except ValueError:
            return str(path)
    else:
        rel = path
    repos = config.get("repos", {})
    inventory_name = repos.get("inventory_name", "fleet-inventory")
    return str(Path(builder["remote_root"]) / inventory_name / rel)


def _kill_process_group(pid: int, sig: int) -> None:
    """Send *sig* to the process group of *pid*."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate_subprocess(proc: subprocess.Popen) -> None:
    """Escalating termination: SIGINT → SIGTERM (5s) → SIGKILL (3s)."""
    _kill_process_group(proc.pid, signal.SIGINT)
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    _kill_process_group(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    _kill_process_group(proc.pid, signal.SIGKILL)
    proc.wait()


def run(argv, *, env=None, cwd=None):
    """Run *argv* with check=True; on Ctrl+C, escalate-kill the child group."""
    printable = " ".join(shlex.quote(str(a)) for a in argv)
    print(f"+ {printable}", file=sys.stderr)
    proc = subprocess.Popen(
        [str(a) for a in argv],
        env=env, cwd=cwd,
        start_new_session=True,
    )
    try:
        proc.wait()
    except KeyboardInterrupt:
        _terminate_subprocess(proc)
        raise
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, argv)


def run_logged(argv, log_path, *, env=None, cwd=None):
    """Run a command while streaming combined output and persisting a log."""
    printable = " ".join(shlex.quote(str(a)) for a in argv)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"+ {printable}", file=sys.stderr)
    proc = subprocess.Popen(
        [str(a) for a in argv],
        env=env,
        cwd=cwd,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"$ {printable}\n")
            for line in proc.stdout or ():
                sys.stderr.write(line)
                sys.stderr.flush()
                log.write(line)
            proc.wait()
    except KeyboardInterrupt:
        _terminate_subprocess(proc)
        raise
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, argv)


def capture(argv, *, env=None, cwd=None):
    """Capture stdout of *argv*; on Ctrl+C, escalate-kill the child group."""
    proc = subprocess.Popen(
        [str(a) for a in argv],
        env=env, cwd=cwd,
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, _ = proc.communicate()
    except KeyboardInterrupt:
        _terminate_subprocess(proc)
        raise
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, argv, output=stdout)
    return stdout


def die(message, code=2):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)
