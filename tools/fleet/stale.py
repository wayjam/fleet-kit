"""Detect stale path fleetkit lock vs on-disk kit tree."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from common import repo_root


def _newest_mtime(root: Path, *, skip_names: frozenset[str]) -> float:
    newest = 0.0
    if not root.is_dir():
        return newest
    for dirpath, dirnames, filenames in os.walk(root):
        # prune
        dirnames[:] = [d for d in dirnames if d not in skip_names and not d.startswith(".")]
        for name in filenames:
            if name.endswith((".pyc", ".pyo")):
                continue
            try:
                m = (Path(dirpath) / name).stat().st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest


def check_path_fleetkit_stale(config, *, stream=None) -> bool:
    """Warn if flake.lock pins an older path fleetkit than the local tree.

    Returns True if a warning was printed.
    """
    stream = stream or sys.stderr
    if os.environ.get("FLEET_SKIP_STALE_CHECK") == "1":
        return False

    root = repo_root()
    lock_path = root / "flake.lock"
    if not lock_path.is_file():
        return False

    input_name = config.get("repos", {}).get("fleetkit_input", "fleetkit")
    try:
        lock = json.loads(lock_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False

    node = lock.get("nodes", {}).get(input_name, {})
    locked = node.get("locked") or {}
    if locked.get("type") != "path":
        return False

    kit_path = locked.get("path")
    if not kit_path:
        return False
    kit = Path(kit_path)
    if not kit.is_dir():
        print(
            f"warning: flake.lock {input_name} path does not exist: {kit}\n"
            f"  fix: update {input_name}.url or restore the directory",
            file=stream,
        )
        return True

    lock_mtime = locked.get("lastModified")
    # lastModified is unix seconds in flake.lock for path inputs
    try:
        lock_ts = float(lock_mtime) if lock_mtime is not None else lock_path.stat().st_mtime
    except (TypeError, ValueError, OSError):
        lock_ts = lock_path.stat().st_mtime

    skip = frozenset({
        ".git",
        "__pycache__",
        "result",
        ".fleet",
        "output",
        "local",
        "node_modules",
    })
    tree_ts = _newest_mtime(kit, skip_names=skip)
    # Allow small skew (editors, NFS)
    if tree_ts <= lock_ts + 2:
        return False

    print(
        f"warning: local {input_name} tree is newer than flake.lock path pin\n"
        f"  kit:  {kit}\n"
        f"  lock lastModified={int(lock_ts)} tree_newest={int(tree_ts)}\n"
        f"  `nix run .#fleet` may use a stale CLI/modules snapshot.\n"
        f"  fix:  nix flake update {input_name}\n"
        f"  skip: FLEET_SKIP_STALE_CHECK=1",
        file=stream,
    )
    return True
