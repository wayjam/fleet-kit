"""Private inventory helpers: init, list, add-host, doctor."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import die, repo_root


# ---------------------------------------------------------------------------
# Template location
# ---------------------------------------------------------------------------


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


def _template_host_dir(kind: str) -> Path:
    mapping = {
        "proxy": "proxy-example",
        "image": "image-example",
    }
    if kind not in mapping:
        die(f"unknown host kind {kind!r}; expected proxy|image")
    path = template_dir() / "hosts" / mapping[kind]
    if not path.is_dir():
        die(f"template host missing: {path}")
    return path


# ---------------------------------------------------------------------------
# Small rewrite helpers
# ---------------------------------------------------------------------------


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
        if "[repos]" in text:
            text = re.sub(
                r"\[repos\]\n",
                f'[repos]\ninventory_name = "{name}"\n',
                text,
                count=1,
            )
            fleet_toml.write_text(text)
            return
        text = text.rstrip() + f'\n\n[repos]\ninventory_name = "{name}"\n'
        fleet_toml.write_text(text)
        return
    fleet_toml.write_text(new)


def _default_fleetkit_url(dest: Path) -> str:
    return "path:../fleet-kit"


def _ignore_symlinks(path: str, names: list[str]) -> set[str]:
    """Skip template symlinks; inventory init recreates managed links later."""
    root = Path(path)
    return {name for name in names if (root / name).is_symlink()}


def _valid_host_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", name))


def _hosts_index(root: Path) -> Path:
    return root / "hosts" / "default.nix"


def _parse_nixos_host_names(index_text: str) -> list[str]:
    """Best-effort list of keys under nixos = { … }."""
    # Match top-level-ish `name = {` under nixos block; skip nested deployment.
    names = []
    in_nixos = False
    depth = 0
    for line in index_text.splitlines():
        if re.search(r"\bnixos\s*=\s*\{", line):
            in_nixos = True
            depth = line.count("{") - line.count("}")
            continue
        if not in_nixos:
            continue
        depth += line.count("{") - line.count("}")
        m = re.match(r"\s*([a-zA-Z][a-zA-Z0-9_-]*)\s*=\s*\{", line)
        if m and depth >= 1:
            key = m.group(1)
            if key not in {"deployment", "path", "image", "tags"}:
                # only record when this opens a host attr (depth after line == 2-ish)
                # After adding host's `{`, depth is typically 2 (nixos + host).
                if depth >= 2:
                    names.append(key)
        if depth <= 0:
            break
    # de-dupe preserve order
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _insert_nixos_host(
    index_text: str,
    host: str,
    *,
    target_host: str,
    target_port: int,
    target_user: str,
    tags: list[str],
    image: bool,
    path_expr: str,
) -> str:
    """Insert a host entry into nixos = { … } before the closing of that attrset."""
    tags_nix = " ".join(json.dumps(t) for t in tags)
    image_line = "      image = true;\n" if image else ""
    block = f"""
    {host} = {{
{image_line}      path = {path_expr};

      deployment = {{
        targetHost = {json.dumps(target_host)};
        targetPort = {target_port};
        targetUser = {json.dumps(target_user)};
        buildOnTarget = true;
        tags = [{tags_nix}];
      }};
    }};
"""
    # Find `nixos = {` then insert before the matching closing `};` at depth 0 of that set.
    m = re.search(r"\bnixos\s*=\s*\{", index_text)
    if not m:
        die("hosts/default.nix: could not find `nixos = {`")
    start = m.end()  # position after `{`
    depth = 1
    i = start
    while i < len(index_text):
        c = index_text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                # insert before this closing brace
                return index_text[:i] + block + index_text[i:]
        i += 1
    die("hosts/default.nix: unbalanced braces in nixos attrset")


def _host_default_nix(
    host: str,
    *,
    kind: str,
    target_port: int,
) -> str:
    """Minimal host module based on proxy-example shape."""
    if kind == "image":
        return f"""{{
  inputs,
  lib,
  pkgs,
  ...
}}: let
  myvars = import ../../vars {{inherit (pkgs) lib;}};
in {{
  imports = [
    inputs.disko.nixosModules.disko
    inputs.fleetkit.nixosModules.profiles-kvm-server
  ];

  system.stateVersion = "25.11";
  networking.hostName = {json.dumps(host)};

  disko = {{
    enableConfig = true;
    devices.disk.main = {{
      device = "/dev/vda";
      type = "disk";
      imageSize = "4G";
      content = {{
        type = "gpt";
        partitions = {{
          bios_boot = {{
            size = "1M";
            type = "EF02";
            priority = 0;
          }};
          root = {{
            name = "NIXROOT";
            size = "100%";
            content = {{
              type = "filesystem";
              format = "ext4";
              mountpoint = "/";
            }};
          }};
        }};
      }};
    }};
  }};

  users.mutableUsers = false;
  users.users = {{
    root = {{
      hashedPassword = myvars.hashedPassword;
      openssh.authorizedKeys.keys = myvars.sshAuthorizedKeys;
    }};
    admin = {{
      isNormalUser = true;
      extraGroups = ["wheel"];
      openssh.authorizedKeys.keys = myvars.sshAuthorizedKeys;
      shell = pkgs.zsh;
    }};
  }};
  programs.zsh.enable = true;

  my.server.ssh = {{
    port = {target_port};
    authorizedKeys = myvars.sshAuthorizedKeys;
    authorizedKeyUsers = ["root" "admin"];
  }};
}}
"""
    # proxy (default)
    return f"""{{
  config,
  inputs,
  pkgs,
  ...
}}: let
  myvars = import ../../vars {{inherit (pkgs) lib;}};
in {{
  imports = [
    inputs.disko.nixosModules.disko
    inputs.sops-nix.nixosModules.sops
    inputs.fleetkit.nixosModules.profiles-kvm-server
    inputs.fleetkit.nixosModules.proxy-xray
    inputs.fleetkit.nixosModules.monitoring-komari-agent
  ];

  system.stateVersion = "25.11";

  my.secrets.sopsAgeKey.enable = true;
  my.server.diskExpansion.enable = true;

  assertions = [
    {{
      assertion = myvars.sshAuthorizedKeys != [];
      message = "{host} requires at least one myvars.sshAuthorizedKeys entry.";
    }}
  ];

  sops.defaultSopsFile = ../../secrets/{host}.yaml;
  # Declare secrets after creating secrets/{host}.yaml, e.g.:
  # sops.secrets.xray_uuid = {{}};

  disko = {{
    enableConfig = true;
    devices.disk.main = {{
      device = "/dev/vda";
      type = "disk";
      imageSize = "4G";
      content = {{
        type = "gpt";
        partitions = {{
          bios_boot = {{
            size = "1M";
            type = "EF02";
            priority = 0;
          }};
          root = {{
            name = "NIXROOT";
            size = "100%";
            content = {{
              type = "filesystem";
              format = "ext4";
              mountpoint = "/";
            }};
          }};
        }};
      }};
    }};
  }};

  users.mutableUsers = false;
  users.users = {{
    root = {{
      hashedPassword = myvars.hashedPassword;
      openssh.authorizedKeys.keys = myvars.sshAuthorizedKeys;
    }};
    admin = {{
      isNormalUser = true;
      extraGroups = ["wheel"];
      openssh.authorizedKeys.keys = myvars.sshAuthorizedKeys;
      shell = pkgs.zsh;
    }};
  }};
  programs.zsh.enable = true;

  my.server.ssh = {{
    port = {target_port};
    authorizedKeys = myvars.sshAuthorizedKeys;
    authorizedKeyUsers = ["root" "admin"];
  }};

  # Enable and configure proxies as needed, e.g. my.proxy.xray = {{ enable = true; … }};
}}
"""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


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

    for entry in src.iterdir():
        target = dest / entry.name
        if entry.is_symlink():
            continue
        if entry.is_dir():
            shutil.copytree(
                entry,
                target,
                dirs_exist_ok=False,
                ignore=_ignore_symlinks,
            )
        else:
            shutil.copy2(entry, target)

    fleetkit_url = args.fleetkit_url or _default_fleetkit_url(dest)
    flake_nix = dest / "flake.nix"
    if flake_nix.is_file():
        _rewrite_fleetkit_url(flake_nix, fleetkit_url)
        print(f'fleet inventory init: fleetkit.url = "{fleetkit_url}"', flush=True)

    inventory_name = args.name or dest.name
    fleet_toml = dest / "fleet.toml"
    _rewrite_inventory_name(fleet_toml, inventory_name)
    print(f'fleet inventory init: inventory_name = "{inventory_name}"', flush=True)

    if args.git:
        if not (dest / ".git").exists():
            subprocess.run(["git", "init"], cwd=dest, check=True)
            print("fleet inventory init: git init", flush=True)

    # Agent skills: symlink to kit (sibling layout ../fleet-kit/skills)
    try:
        kit_skills = dest.parent / "fleet-kit" / "skills"
        if kit_skills.is_dir():
            link_inventory_skills(dest, kit_skills=kit_skills)
        else:
            print(
                "fleet inventory init: skip skills-link (no sibling fleet-kit/skills); "
                "run: just skills-link later",
                flush=True,
            )
    except Exception as exc:
        print(f"fleet inventory init: skills-link failed: {exc}", flush=True)

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


def cmd_inventory_list(args, config):
    root = repo_root()
    index = _hosts_index(root)
    if not index.is_file():
        die(f"missing {index}; run from a private inventory repo")
    text = index.read_text()
    names = _parse_nixos_host_names(text)
    if not names:
        print("(no nixos hosts found in hosts/default.nix)", flush=True)
        return
    for name in names:
        path = root / "hosts" / name
        kind = "dir" if path.is_dir() else ("file" if (root / "hosts" / f"{name}.nix").is_file() else "?")
        secret = root / "secrets" / f"{name}.yaml"
        sec = "secrets=yes" if secret.is_file() else "secrets=no"
        print(f"{name}\t{kind}\t{sec}", flush=True)


def cmd_inventory_add_host(args, config):
    root = repo_root()
    host = args.host
    if not _valid_host_name(host):
        die(f"invalid host name {host!r}; use [a-zA-Z][a-zA-Z0-9_-]*")

    index = _hosts_index(root)
    if not index.is_file():
        die(f"missing {index}; run from a private inventory repo")

    if host in _parse_nixos_host_names(index.read_text()):
        die(f"host already registered in hosts/default.nix: {host}")

    host_dir = root / "hosts" / host
    host_file = root / "hosts" / f"{host}.nix"
    if host_dir.exists() or host_file.exists():
        die(f"host path already exists: {host_dir if host_dir.exists() else host_file}")

    kind = args.kind
    target_host = args.target_host or "203.0.113.10"
    target_port = int(args.target_port)
    target_user = args.target_user
    tags = list(args.tag) if args.tag else [kind, "kvm"]
    image = kind == "image" or args.image

    # Prefer copy-from-template when --from-template; else generate minimal module.
    host_dir.mkdir(parents=True, exist_ok=False)
    if args.from_template:
        src = _template_host_dir(kind)
        for entry in src.iterdir():
            dest = host_dir / entry.name
            if entry.is_dir():
                shutil.copytree(entry, dest)
            else:
                shutil.copy2(entry, dest)
        # light rewrite hostname / sops file name if present
        default_nix = host_dir / "default.nix"
        if default_nix.is_file():
            text = default_nix.read_text()
            text = text.replace("proxy-example", host).replace("image-example", host)
            text = re.sub(
                r"secrets/[a-zA-Z0-9._-]+\.yaml",
                f"secrets/{host}.yaml",
                text,
            )
            if target_port != 2234:
                text = re.sub(
                    r"(port\s*=\s*)\d+(\s*;)",
                    rf"\g<1>{target_port}\2",
                    text,
                    count=1,
                )
            default_nix.write_text(text)
        print(f"fleet inventory add-host: copied template {kind} → hosts/{host}/", flush=True)
    else:
        (host_dir / "default.nix").write_text(
            _host_default_nix(host, kind=kind, target_port=target_port)
        )
        print(f"fleet inventory add-host: wrote hosts/{host}/default.nix", flush=True)

    # secrets placeholder
    secrets_dir = root / "secrets"
    secrets_dir.mkdir(exist_ok=True)
    secret_path = secrets_dir / f"{host}.yaml"
    if not secret_path.exists() and kind == "proxy":
        secret_path.write_text(
            f"# Create with: sops secrets/{host}.yaml\n"
            f"# or: nix run .#fleet -- age create {host}\n"
        )
        print(f"fleet inventory add-host: placeholder {secret_path.relative_to(root)}", flush=True)

    # register in hosts/default.nix
    index_text = index.read_text()
    new_text = _insert_nixos_host(
        index_text,
        host,
        target_host=target_host,
        target_port=target_port,
        target_user=target_user,
        tags=tags,
        image=image,
        path_expr=f"./{host}",
    )
    index.write_text(new_text)
    print(f"fleet inventory add-host: registered {host} in hosts/default.nix", flush=True)
    print(
        "\nNext:\n"
        f"  # edit hosts/{host}/default.nix\n"
        f"  sops secrets/{host}.yaml   # if using sops\n"
        f"  git add hosts/{host} hosts/default.nix secrets/{host}.yaml\n"
        "  just eval\n",
        flush=True,
    )


def cmd_inventory_doctor(args, config):
    root = repo_root()
    issues = []
    warns = []
    oks = []

    def ok(msg):
        oks.append(msg)

    def warn(msg):
        warns.append(msg)

    def bad(msg):
        issues.append(msg)

    # fleet.toml
    fleet_toml = root / "fleet.toml"
    if fleet_toml.is_file():
        ok("fleet.toml present")
        text = fleet_toml.read_text()
        m = re.search(r'inventory_name\s*=\s*"([^"]+)"', text)
        if m:
            inv = m.group(1)
            if inv != root.name:
                warn(
                    f"repos.inventory_name={inv!r} != directory name {root.name!r} "
                    "(builder sync uses sibling folder name)"
                )
            else:
                ok(f"inventory_name matches directory ({inv})")
        else:
            warn("repos.inventory_name not set in fleet.toml")
        m = re.search(r'public_name\s*=\s*"([^"]+)"', text)
        if m:
            pub = m.group(1)
            sibling = root.parent / pub
            if sibling.is_dir():
                ok(f"public sibling exists: {sibling}")
            else:
                warn(f"public sibling missing: {sibling} (ok if fleetkit is github URL)")
    else:
        bad("missing fleet.toml")

    # flake
    flake = root / "flake.nix"
    lock = root / "flake.lock"
    if not flake.is_file():
        bad("missing flake.nix")
    else:
        ok("flake.nix present")
        ftext = flake.read_text()
        if "fleetkit" not in ftext and "dotfiles" in ftext:
            bad("flake.nix still uses inputs.dotfiles; rename to fleetkit")
        elif "fleetkit" in ftext:
            ok("flake.nix references fleetkit")
        m = re.search(r'fleetkit\.url\s*=\s*"([^"]+)"', ftext)
        if m:
            url = m.group(1)
            if url.startswith("path:/Users/") or url.startswith("path:/home/"):
                warn(
                    f"fleetkit.url is absolute path ({url}); "
                    "fine on this machine, brittle on others"
                )
            else:
                ok(f"fleetkit.url = {url}")

    if lock.is_file():
        ok("flake.lock present")
        try:
            data = json.loads(lock.read_text())
            node = data.get("nodes", {}).get("fleetkit", {})
            locked = node.get("locked") or {}
            kind = locked.get("type")
            if kind == "path":
                ok(f"flake.lock fleetkit type=path ({locked.get('path', '')})")
                # stale check vs local path mtime is done more fully by doctor/builder;
                # light note here
            elif kind in {"github", "git", "gitlab", "sourcehut"}:
                ok(f"flake.lock fleetkit type={kind}")
            elif kind:
                warn(f"flake.lock fleetkit type={kind!r}")
            else:
                warn("flake.lock has no fleetkit node")
        except json.JSONDecodeError as exc:
            bad(f"flake.lock invalid JSON: {exc}")
    else:
        warn("missing flake.lock (run nix flake lock)")

    # hosts
    index = _hosts_index(root)
    if not index.is_file():
        bad("missing hosts/default.nix")
    else:
        names = _parse_nixos_host_names(index.read_text())
        ok(f"hosts/default.nix: {len(names)} nixos host(s)")
        for name in names:
            hdir = root / "hosts" / name
            hfile = root / "hosts" / f"{name}.nix"
            if not hdir.is_dir() and not hfile.is_file():
                bad(f"host {name} registered but hosts/{name}/ or .nix missing")
            secret = root / "secrets" / f"{name}.yaml"
            # only warn if host module mentions sops
            host_nix = hdir / "default.nix" if hdir.is_dir() else hfile
            if host_nix.is_file() and "sops" in host_nix.read_text():
                if not secret.is_file():
                    bad(f"host {name} uses sops but secrets/{name}.yaml missing")
                else:
                    # git tracked?
                    try:
                        r = subprocess.run(
                            ["git", "ls-files", "--error-unmatch", str(secret.relative_to(root))],
                            cwd=root,
                            capture_output=True,
                            text=True,
                        )
                        if r.returncode != 0:
                            warn(f"secrets/{name}.yaml exists but not git-tracked")
                        else:
                            ok(f"secrets/{name}.yaml tracked")
                    except FileNotFoundError:
                        warn("git not available; skip secret track check")

    # sops.yaml
    if (root / ".sops.yaml").is_file():
        ok(".sops.yaml present")
    else:
        warn("missing .sops.yaml (needed for sops secrets)")

    # print report
    for msg in oks:
        print(f"  ok  {msg}")
    for msg in warns:
        print(f" WARN {msg}", file=sys.stderr)
    for msg in issues:
        print(f" FAIL {msg}", file=sys.stderr)
    print(
        f"\nfleet inventory doctor: {len(oks)} ok, {len(warns)} warn, {len(issues)} fail",
        flush=True,
    )
    if issues:
        sys.exit(1)




def kit_skills_root() -> Path:
    """Resolve fleet-kit/skills from env, sibling, or source layout."""
    env = os.environ.get("FLEET_KIT_SKILLS_DIR")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p
    # sibling of inventory cwd
    sibling = repo_root().parent / "fleet-kit" / "skills"
    if sibling.is_dir():
        return sibling
    # from tools/fleet -> ../../skills
    here = Path(__file__).resolve().parent
    cand = here.parent.parent / "skills"
    if cand.is_dir():
        return cand
    # template dir parent
    try:
        t = template_dir().parent.parent / "skills"  # templates/ -> kit root
        if t.is_dir():
            return t
    except Exception:
        pass
    die(
        "cannot find fleet-kit/skills; set FLEET_KIT_SKILLS_DIR or place inventory "
        "next to fleet-kit"
    )


def link_inventory_skills(dest: Path | None = None, *, kit_skills: Path | None = None) -> None:
    """Create skills/* symlinks to kit and .claude/skills -> ../skills."""
    root = dest or repo_root()
    kit_skills = kit_skills or kit_skills_root()
    skills_dir = root / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for name in ("add-host", "debug-deploy"):
        src = kit_skills / name
        if not src.is_dir():
            print(f"warning: missing kit skill {src}", flush=True)
            continue
        link = skills_dir / name
        # relative target from skills/name -> kit skill
        try:
            rel = os.path.relpath(src, start=skills_dir)
        except ValueError:
            rel = str(src)
        if link.is_symlink() or link.exists():
            if link.is_symlink() or link.is_dir():
                if link.is_symlink():
                    link.unlink()
                else:
                    # do not delete real dirs with content
                    print(f"warning: {link} exists and is not a symlink; skip", flush=True)
                    continue
        link.symlink_to(rel, target_is_directory=True)
        print(f"fleet skills-link: {link} -> {rel}", flush=True)

    claude = root / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    claude_skills = claude / "skills"
    if claude_skills.is_symlink():
        claude_skills.unlink()
    elif claude_skills.exists():
        print(f"warning: {claude_skills} exists and is not a symlink; skip", flush=True)
        return
    claude_skills.symlink_to("../skills", target_is_directory=True)
    print(f"fleet skills-link: {claude_skills} -> ../skills", flush=True)


def cmd_inventory_skills_link(args, config):
    link_inventory_skills()


def cmd_inventory(args, config):
    """Dispatch inventory subcommands (set by argparse)."""
    cmd = getattr(args, "inventory_command", None)
    if cmd == "init":
        return cmd_inventory_init(args, config)
    if cmd == "list":
        return cmd_inventory_list(args, config)
    if cmd == "add-host":
        return cmd_inventory_add_host(args, config)
    if cmd == "doctor":
        return cmd_inventory_doctor(args, config)
    if cmd == "skills-link":
        return cmd_inventory_skills_link(args, config)
    die(f"unknown inventory command: {cmd}")
