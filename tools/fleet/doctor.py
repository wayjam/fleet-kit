"""`fleet doctor` — environment and builder diagnostics."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from builder import (
    apply_builder_overrides,
    builder_config,
    detect_fleetkit_mode,
    fleetkit_input_name,
    remote_nix_expr,
    resolve_sync_method,
    ssh_args,
    _local_has_rsync,
    _remote_has_rsync,
)
from common import die, repo_root
from inventory import cmd_inventory_doctor
from stale import check_path_fleetkit_stale


def cmd_doctor(args, config):
    target = getattr(args, "doctor_target", None) or "all"
    if target == "inventory":
        return cmd_inventory_doctor(args, config)
    if target == "builder":
        return _doctor_builder(args, config)
    if target == "all":
        print("== inventory ==", flush=True)
        try:
            cmd_inventory_doctor(args, config)
            inv_rc = 0
        except SystemExit as exc:
            inv_rc = exc.code if isinstance(exc.code, int) else 1
        print("\n== local / lock ==", flush=True)
        _doctor_local(config)
        if getattr(args, "builder", None) or config.get("builder", {}).get("default"):
            print("\n== builder ==", flush=True)
            try:
                _doctor_builder(args, config)
                b_rc = 0
            except SystemExit as exc:
                b_rc = exc.code if isinstance(exc.code, int) else 1
        else:
            print("(no default builder; skip builder checks)", flush=True)
            b_rc = 0
        if inv_rc or b_rc:
            sys.exit(1)
        return
    die(f"unknown doctor target: {target}")


def _doctor_local(config):
    check_path_fleetkit_stale(config)
    mode = detect_fleetkit_mode(config)
    print(f"  ok  fleetkit_mode={mode} input={fleetkit_input_name(config)}")
    local_rsync = _local_has_rsync()
    print(f"  ok  local rsync={'yes' if local_rsync else 'no'}")
    for name in ("nix", "sops", "ssh", "tar"):
        path = shutil.which(name)
        if path:
            print(f"  ok  {name}={path}")
        else:
            print(f" WARN {name} not on PATH", file=sys.stderr)


def _doctor_builder(args, config):
    name = getattr(args, "builder", None) or None
    if name == "":
        name = None
    builder = apply_builder_overrides(builder_config(config, name), args)
    issues = 0

    print(f"  ok  builder alias={builder.get('alias')} host={builder.get('host')}:{builder.get('port')}")
    print(f"  ok  remote_root={builder.get('remote_root')}")

    # SSH connectivity
    try:
        subprocess.run(
            [*ssh_args(builder), "true"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        print("  ok  ssh connectivity")
    except subprocess.CalledProcessError as exc:
        print(f" FAIL ssh: {exc.stderr or exc}", file=sys.stderr)
        issues += 1
        sys.exit(1)

    local_rsync = _local_has_rsync()
    remote_rsync = _remote_has_rsync(builder)
    print(f"  ok  rsync local={'yes' if local_rsync else 'no'} remote={'yes' if remote_rsync else 'no'}")
    method = resolve_sync_method(config, builder)
    print(f"  ok  sync_method resolved={method}")

    # remote nix
    probe = (
        f"set -eu; remote_nix={remote_nix_expr(builder)}; "
        f"echo nix=$remote_nix; $remote_nix --version | head -1"
    )
    try:
        out = subprocess.run(
            [*ssh_args(builder), probe],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in out.stdout.strip().splitlines():
            print(f"  ok  remote {line}")
    except subprocess.CalledProcessError as exc:
        print(f" FAIL remote nix: {exc.stderr or exc}", file=sys.stderr)
        issues += 1

    # disk space in remote_root
    remote_root = builder["remote_root"]
    try:
        out = subprocess.run(
            [*ssh_args(builder), f"df -h {remote_root} | tail -1"],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"  ok  disk {out.stdout.strip()}")
    except subprocess.CalledProcessError:
        print(" WARN could not read remote df", file=sys.stderr)

    repos = config.get("repos", {})
    inv = repos.get("inventory_name", "fleet-inventory")
    pub = repos.get("public_name", "fleet-kit")
    mode = detect_fleetkit_mode(config)
    print(f"  ok  would sync inventory={inv}" + (f" + public={pub}" if mode == "path" else " (kit remote-fetch)"))

    if issues:
        sys.exit(1)
