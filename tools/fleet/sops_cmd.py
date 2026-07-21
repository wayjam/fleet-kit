"""`fleet sops rekey` / `fleet sops rotate-hint` — sops maintenance helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from common import die, repo_root
from inventory import _parse_nixos_host_names, _hosts_index
from nix import sops_env


def cmd_sops(args, config):
    sub = getattr(args, "sops_command", None)
    if sub == "rekey":
        return cmd_sops_rekey(args, config)
    if sub == "rotate-hint":
        return cmd_sops_rotate_hint(args, config)
    die(f"unknown sops command: {sub}")


def _secret_files(root: Path, host: str | None) -> list[Path]:
    secrets = root / "secrets"
    if not secrets.is_dir():
        die(f"missing {secrets}")
    if host:
        path = secrets / f"{host}.yaml"
        if not path.is_file():
            die(f"missing {path}")
        return [path]
    return sorted(secrets.glob("*.yaml"))


def cmd_sops_rekey(args, config):
    """Re-encrypt secrets with current .sops.yaml recipients (sops updatekeys)."""
    root = repo_root()
    sops_yaml = root / ".sops.yaml"
    if not sops_yaml.is_file():
        die("missing .sops.yaml")

    files = _secret_files(root, getattr(args, "host", None))
    if not files:
        print("no secrets/*.yaml to rekey", flush=True)
        return

    env = sops_env(config)
    dry = getattr(args, "dry_run", False)
    for path in files:
        rel = path.relative_to(root)
        if dry:
            print(f"would rekey {rel}", flush=True)
            continue
        # sops updatekeys -y re-encrypts in place per creation_rules
        cmd = ["sops", "updatekeys", "-y", str(path)]
        print(f"+ {' '.join(cmd)}", file=sys.stderr)
        try:
            subprocess.run(cmd, cwd=root, check=True, env=env)
            print(f"rekeyed {rel}", flush=True)
        except FileNotFoundError:
            die("sops not found on PATH")
        except subprocess.CalledProcessError as exc:
            die(f"sops updatekeys failed for {rel} (exit {exc.returncode})")


def cmd_sops_rotate_hint(args, config):
    """Print a safe checklist for rotating age keys (does not rewrite keys for you)."""
    root = repo_root()
    print(
        """fleet sops rotate-hint — age key rotation checklist

1. Generate a new admin age key:
     nix run .#fleet -- secret age-file admin-new
   (or: age-keygen -o local/keys/admin-new.agekey)

2. Add the new public key to .sops.yaml (keep the old one temporarily).

3. Re-encrypt all host secrets with both recipients:
     nix run .#fleet -- sops rekey
   # or one host:
     nix run .#fleet -- sops rekey --host hostsailor-lax

4. Verify decrypt still works:
     SOPS_AGE_KEY_FILE=local/keys/admin-new.agekey sops -d secrets/<host>.yaml | head

5. Remove the old recipient from .sops.yaml and rekey again:
     nix run .#fleet -- sops rekey

6. Update node keys on servers if you rotated the node age key
   (my.secrets.sopsAgeKey / /etc/sops/age/key.txt) and redeploy.

7. git add .sops.yaml secrets/*.yaml && git commit

Note: this command does not rewrite private keys. It only prints the procedure.
""",
        flush=True,
    )
    index = _hosts_index(root)
    if index.is_file():
        hosts = _parse_nixos_host_names(index.read_text())
        print(f"hosts in inventory: {', '.join(hosts) if hosts else '(none)'}", flush=True)
    secrets = list((root / "secrets").glob("*.yaml")) if (root / "secrets").is_dir() else []
    print(f"secret files: {len(secrets)}", flush=True)
