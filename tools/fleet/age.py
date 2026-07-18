"""`fleet age` — small sops host-secret helper."""

import getpass
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from common import die, repo_path, repo_root
from nix import sops_env


def _split_target(value):
    if "/" in value or value.endswith((".yaml", ".yml")):
        return value, None
    if "." in value:
        host, key = value.rsplit(".", 1)
        if host and key:
            return host, key
    return value, None


def _target(args):
    target, key = _split_target(args.target)
    for item in getattr(args, "rest", []):
        if item.startswith("key="):
            key = item.split("=", 1)[1]
        else:
            die(f"unknown argument: {item}")

    path = Path(target).expanduser()
    if not path.is_absolute():
        if "/" not in target and not target.endswith((".yaml", ".yml")):
            path = repo_root() / "secrets" / f"{target}.yaml"
        else:
            path = repo_path(path)

    if not path.exists() and args.age_command != "create":
        die(f"missing secret file: {path}")
    return path, key


def _load(path, config):
    result = subprocess.check_output(
        ["sops", "-d", "--output-type", "json", path],
        env=sops_env(config),
        text=True,
    )
    data = json.loads(result)
    if not isinstance(data, dict):
        die(f"{path} must decrypt to a YAML/JSON mapping")
    return data


def _save(path, data, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        json.dump(data, f)
        tmp = f.name
    try:
        try:
            override = str(path.relative_to(repo_root()))
        except ValueError:
            override = str(path)
        subprocess.check_call(
            [
                "sops",
                "--encrypt",
                "--filename-override",
                override,
                "--input-type",
                "json",
                "--output-type",
                "yaml",
                "--output",
                path,
                tmp,
            ],
            env=sops_env(config),
        )
    finally:
        Path(tmp).unlink(missing_ok=True)


def _read_new_value():
    if not sys.stdin.isatty():
        return sys.stdin.read().rstrip("\n")
    return getpass.getpass("value: ")


def _edit_value(value):
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write(str(value))
        f.write("\n")
        tmp = f.name
    try:
        subprocess.check_call([editor, tmp])
        return Path(tmp).read_text().rstrip("\n")
    finally:
        Path(tmp).unlink(missing_ok=True)


def cmd_age(args, config):
    path, key = _target(args)
    data = {} if args.age_command == "create" and not path.exists() else _load(path, config)

    if args.age_command == "list":
        keys = sorted(data)
        if key:
            if key not in data:
                die(f"missing key: {key}")
            keys = [key]
        print("\n".join(keys))
        return

    if not key:
        die("missing key; use <host>.<key> or <host> key=<key>")

    if args.age_command == "read":
        if key not in data:
            die(f"missing key: {key}")
        print(data[key])
        return

    if args.age_command == "create":
        if key in data:
            die(f"{key} already exists; use edit")
        data[key] = _read_new_value()
        _save(path, data, config)
        print(f"created {path}:{key}")
        return

    if args.age_command == "edit":
        if key not in data:
            die(f"missing key: {key}; use create")
        data[key] = _edit_value(data[key])
        _save(path, data, config)
        print(f"edited {path}:{key}")
        return

    die(f"unknown age command: {args.age_command}")
