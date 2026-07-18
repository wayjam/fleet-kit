"""Nix / sops evaluation helpers.

Thin wrappers over `nix eval` and `sops -d`, plus host-config evaluators that
the command modules consume (build, profile, ports, infect, ...).
"""

import json
import os
import subprocess
from pathlib import Path

from common import capture, die, repo_path, repo_root


def colmena_cmd():
    return ["nix", "run", ".#colmena", "--", "--impure", "--config", "flake.nix"]


def nixos_anywhere_cmd():
    return ["nix", "run", ".#nixos-anywhere", "--"]


def nix_eval_json(attr):
    return json.loads(capture(["nix", "eval", attr, "--json"]))


def maybe_nix_eval_json(attr):
    result = subprocess.run(["nix", "eval", attr, "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def nix_eval_raw(attr):
    return capture(["nix", "eval", attr, "--raw"]).strip()


def sops_env(config):
    env = os.environ.copy()
    if not any(env.get(name) for name in ("SOPS_AGE_KEY_FILE", "SOPS_AGE_KEY", "SOPS_AGE_KEY_CMD")):
        paths = config.get("paths", {})
        candidates = [
            repo_path(paths.get("node_age_key", "local/node-age.txt")),
            repo_path(Path(paths.get("secret_key_dir", "local/keys")) / "admin.agekey"),
        ]
        for key_file in candidates:
            if key_file.exists():
                env["SOPS_AGE_KEY_FILE"] = str(key_file)
                break
    return env


def host_secret_file(host):
    path = repo_root() / "secrets" / f"{host}.yaml"
    if not path.exists():
        die(f"missing host secret file: {path}")
    return path


def load_host_secrets(host, config):
    output = capture(
        ["sops", "-d", "--output-type", "json", host_secret_file(host)],
        env=sops_env(config),
    )
    return json.loads(output)


def secret_key_from_runtime_path(path):
    if not path:
        return None
    return Path(path).name


def secret_value(secrets, runtime_path, description):
    key = secret_key_from_runtime_path(runtime_path)
    if not key:
        die(f"missing runtime secret path for {description}")
    value = secrets.get(key)
    if not value:
        die(f"missing {key} in decrypted secrets for {description}")
    return str(value).strip()


def host_deployment(host):
    deployment = maybe_nix_eval_json(f".#colmena.{host}.deployment")
    if not deployment:
        die(f"missing colmena deployment for host: {host}")
    return deployment


def eval_host_json(host, path, default):
    value = maybe_nix_eval_json(f".#nixosConfigurations.{host}.config.{path}")
    return default if value is None else value


def eval_host_raw(host, path, default=""):
    try:
        return nix_eval_raw(f".#nixosConfigurations.{host}.config.{path}")
    except subprocess.CalledProcessError:
        return default


def host_target(host):
    return nix_eval_raw(f".#colmena.{host}.deployment.targetHost")
