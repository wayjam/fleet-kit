"""`fleet inventory init` — scaffold a private inventory from the kit template."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from common import die


def template_dir() -> Path:
    """Locate templates/fleet-inventory.

    Prefer FLEET_KIT_TEMPLATE_DIR (set by the flake wrapper). Fall back to
    resolving relative to a source checkout (…/fleet-kit/tools/fleet → …/templates).
    """
    env = os.environ.get("FLEET_KIT_TEMPLATE_DIR")
    if env:
        path = Path(env).expanduser().resolve()
        if path.is_dir():
            return path
        die(f"FLEET_KIT_TEMPLATE_DIR is not a directory: {path}")

    here = Path(__file__).resolve().parent  # …/tools/fleet
    candidates = [
        here.parent.parent / "templates" / "fleet-inventory",  # kit checkout
        here.parent / "templates" / "fleet-inventory",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    die(
        "cannot find templates/fleet-inventory; run via `nix run .#fleet` from "
        "fleet-kit (sets FLEET_KIT_TEMPLATE_DIR), or set FLEET_KIT_TEMPLATE_DIR"
    )


def _rewrite_fleetkit_url(flake_nix: Path, url: str) -> None:
    text = flake_nix.read_text()
    new, n = re.subn(
        r'(fleetkit\.url\s*=\s*")[^"]*(")',
        rf"\g<1>{url}\2",
        text,
        count=1,
    )
    if n != 1:
        die(f"could not rewrite fleetkit.url in {flake_nix}")
    flake_nix.write_text(new)


def _rewrite_inventory_name(fleet_toml: Path, name: str) -> None:
    if not fleet_toml.is_file():
        return
    text = fleet_toml.read_text()
    new, n = re.subn(
        r'(inventory_name\s*=\s*")[^"]*(")',
        rf"\g<1>{name}\2",
        text,
        count=1,
    )
    if n == 0:
        # append under [repos] if missing
        if "[repos]" in text:
            text = text.replace(
                "[repos]",
                f'[repos]\ninventory_name = "{name}"',
                1,
            )
            # might duplicate [repos] content awkwardly if inventory_name exists with spaces
            fleet_toml.write_text(text)
            return
        text = text.rstrip() + f'\n\n[repos]\ninventory_name = "{name}"\n'
        fleet_toml.write_text(text)
        return
    fleet_toml.write_text(new)


def _default_fleetkit_url(dest: Path) -> str:
    """Prefer path:../fleet-kit when a sibling fleet-kit directory exists."""
    sibling = dest.resolve().parent / "fleet-kit"
    if sibling.is_dir():
        return "path:../fleet-kit"
    return "path:../fleet-kit"


def cmd_inventory_init(args, config):
    dest = Path(args.directory).expanduser()
    if not dest.is_absolute():
        dest = Path.cwd() / dest
    dest = dest.resolve()

    if dest.exists():
        if any(dest.iterdir()):
            die(f"destination is not empty: {dest}")
    else:
        dest.mkdir(parents=True, exist_ok=False)

    src = template_dir()
    print(f"fleet inventory init: template={src}", flush=True)
    print(f"fleet inventory init: destination={dest}", flush=True)

    # copytree into dest (dest must exist and be empty)
    for entry in src.iterdir():
        target = dest / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=False)
        else:
            shutil.copy2(entry, target)

    fleetkit_url = args.fleetkit_url or _default_fleetkit_url(dest)
    flake_nix = dest / "flake.nix"
    if flake_nix.is_file():
        _rewrite_fleetkit_url(flake_nix, fleetkit_url)
        print(f"fleet inventory init: fleetkit.url = \"{fleetkit_url}\"", flush=True)

    inventory_name = args.name or dest.name
    fleet_toml = dest / "fleet.toml"
    _rewrite_inventory_name(fleet_toml, inventory_name)
    print(f"fleet inventory init: inventory_name = \"{inventory_name}\"", flush=True)

    if args.git:
        if not (dest / ".git").exists():
            subprocess.run(["git", "init"], cwd=dest, check=True)
            print("fleet inventory init: git init", flush=True)

    if args.lock:
        print("fleet inventory init: nix flake lock …", flush=True)
        subprocess.run(["nix", "flake", "lock"], cwd=dest, check=True)

    print(
        "\nNext steps:\n"
        f"  cd {dest}\n"
        "  # edit hosts/, .sops.yaml, secrets/\n"
        "  nix flake lock   # if you skipped --lock\n"
        "  just eval\n",
        flush=True,
    )
