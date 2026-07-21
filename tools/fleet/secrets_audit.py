"""`fleet secrets audit` — compare sops.secrets declarations vs secrets/*.yaml keys."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from common import die, repo_root
from inventory import _parse_nixos_host_names, _hosts_index
from nix import sops_env


def _declared_sops_keys(host_nix: Path) -> set[str]:
    """Parse sops.secrets.<name> = from host nix files (best-effort)."""
    text = host_nix.read_text()
    keys = set(re.findall(r"sops\.secrets\.([a-zA-Z0-9_]+)\s*=", text))
    # also sops.secrets."quoted"
    keys.update(re.findall(r'sops\.secrets\."([^"]+)"\s*=', text))
    return keys


def _yaml_top_level_keys(path: Path, config) -> set[str] | None:
    """Decrypt and list top-level keys; None if cannot decrypt."""
    try:
        out = subprocess.run(
            ["sops", "-d", "--output-type", "json", str(path)],
            check=True,
            capture_output=True,
            text=True,
            env=sops_env(config),
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    import json

    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return set()
    # sops metadata key
    return {k for k in data if k != "sops"}


def _host_nix_path(root: Path, host: str) -> Path | None:
    d = root / "hosts" / host / "default.nix"
    if d.is_file():
        return d
    f = root / "hosts" / f"{host}.nix"
    if f.is_file():
        return f
    return None


def cmd_secrets_audit(args, config):
    root = repo_root()
    index = _hosts_index(root)
    if not index.is_file():
        die("missing hosts/default.nix")

    hosts = [args.host] if getattr(args, "host", None) else _parse_nixos_host_names(index.read_text())
    if not hosts:
        print("no hosts to audit", flush=True)
        return

    fails = 0
    for host in hosts:
        nix_path = _host_nix_path(root, host)
        if not nix_path:
            print(f"{host}: FAIL missing host module", file=sys.stderr)
            fails += 1
            continue
        declared = _declared_sops_keys(nix_path)
        if not declared:
            print(f"{host}: ok  (no sops.secrets.* declarations)")
            continue

        secret_file = root / "secrets" / f"{host}.yaml"
        if not secret_file.is_file():
            print(f"{host}: FAIL declared {sorted(declared)} but secrets/{host}.yaml missing", file=sys.stderr)
            fails += 1
            continue

        keys = _yaml_top_level_keys(secret_file, config)
        if keys is None:
            print(
                f"{host}: WARN cannot decrypt secrets/{host}.yaml "
                f"(declared={sorted(declared)}); set SOPS_AGE_KEY_FILE?",
                file=sys.stderr,
            )
            continue

        missing = declared - keys
        extra = keys - declared
        if not missing and not extra:
            print(f"{host}: ok  {len(declared)} secret(s) match")
            continue
        if missing:
            print(f"{host}: FAIL declared but missing in yaml: {sorted(missing)}", file=sys.stderr)
            fails += 1
        if extra:
            print(f"{host}: WARN in yaml but not declared in nix: {sorted(extra)}", file=sys.stderr)

    if fails:
        sys.exit(1)
