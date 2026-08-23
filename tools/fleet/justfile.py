"""`fleet justfile render` — emit the Justfile template (source of truth).

The generated Justfile in a private inventory is produced by `just up`, which
runs `fleet justfile render --output Justfile`.
"""

from pathlib import Path

JUSTFILE_TEMPLATE = """# Fleet Justfile shortcuts.
#
# Recipes keep only required positional arguments and pass optional flags through
# to the Python CLI. Use normal fleet flags after the required args:
#   just image panstar-hks --builder builder --no-kvm
#   just deploy panstar-hks --builder builder --retry 1
#   just inventory-add-host my-vps --target-host 1.2.3.4 --kind proxy
#   just sync --builder default --dry-run
#
# For full options:
#   just image <host> --help
#   nix run .#fleet -- image --help
#   nix run .#fleet -- inventory --help
#
# Private-only recipes (e.g. darwin-build) live in Justfile.local and are
# pulled in via `import?` below. `just up` only rewrites this file — Justfile.local
# is never touched.

default:
  @just --list

############################################################################
# core
############################################################################

# Format all Nix files.
fmt:
  nix run .#fleet -- fmt

# Run flake checks (--show-trace).
check:
  nix run .#fleet -- check

# Evaluate all fleet outputs (list node names).
eval:
  nix run .#fleet -- eval

# Build a host system closure — `just build <host> [fleet flags...]`
build host *args:
  nix run .#fleet -- build {{host}} {{args}}

# Check SSH + nix connectivity to a remote builder — `just builder-ping [builder] [fleet flags...]`
builder-ping *args:
  nix run .#fleet -- builder-ping {{args}}

############################################################################
# inventory lifecycle
############################################################################

# List nixos hosts in hosts/default.nix
inventory-list:
  nix run .#fleet -- inventory list

# Add a host skeleton — `just inventory-add-host my-vps --target-host 1.2.3.4 --kind proxy`
inventory-add-host host *args:
  nix run .#fleet -- inventory add-host {{host}} {{args}}

# Check inventory layout, fleetkit input, secrets tracking
inventory-doctor:
  nix run .#fleet -- inventory doctor

# Full doctor (inventory + lock + builder if configured)
doctor *args:
  nix run .#fleet -- doctor {{args}}

############################################################################
# builder sync
############################################################################

# Sync worktree to builder — `just sync --builder default` or `just sync --dry-run --builder default`
sync *args:
  nix run .#fleet -- sync {{args}}

############################################################################
# deploy / install / image
############################################################################

# Deploy to a host (stages: sync→lock→apply) — `just deploy <target> [fleet flags...]`
deploy target *args:
  nix run .#fleet -- deploy {{target}} {{args}}

# Deploy to all Colmena hosts (stages: sync→lock→apply) — `just deploy-all [fleet flags...]`
deploy-all *args:
  nix run .#fleet -- deploy-all {{args}}

# Colmena dry-activate (no apply) — `just diff <host>`
diff host *args:
  nix run .#fleet -- diff {{host}} {{args}}

# Build a disko image (stages: sync→remote-build→verify) — `just image <host> [fleet flags...]`
image host *args:
  nix run .#fleet -- image {{host}} {{args}}

# Download remote-built disko image via SCP — `just download-image <host> [fleet flags...]`
download-image host *args:
  nix run .#fleet -- download-image {{host}} {{args}}

# Convert Debian/Ubuntu → NixOS — `just infect <host> [fleet flags...]`
infect host *args:
  nix run .#fleet -- infect {{host}} {{args}}

# Fresh NixOS install via nixos-anywhere — `just install <host> [fleet flags...]`
# ARM example: `just install orcl-nl-arm --ssh-target root@141.144.197.33:2234 --backup-ref oci://... --dry-run`
# Installation stages: preflight → prepare-target → kexec → disko → install → verify.
# Real destructive runs require --backup-ref (or explicit --allow-no-backup).
install host *args:
  nix run .#fleet -- install {{host}} {{args}}

# Switch a system-manager LXC or existing Linux host — `just lxc-switch <host>`
lxc-switch host:
  nix run .#fleet -- lxc-switch {{host}}

############################################################################
# observe / secrets
############################################################################

# Print allowed TCP & UDP firewall ports — `just ports <host>`
ports host:
  nix run .#fleet -- ports {{host}}

# Show client proxy/VPN profiles — `just profile <host> [fleet flags...]`
profile host *args:
  nix run .#fleet -- profile {{host}} {{args}}

# Manage remote builder jobs — `just jobs list|status|log|cancel|cleanup --builder <x> [args...]`
jobs *args:
  nix run .#fleet -- jobs {{args}}

# Generate secrets — `just secret uuid | password | hex | …`
secret +args:
  nix run .#fleet -- secret {{args}}

# Read and edit encrypted host secrets — `just age list <host>`, `just age read <host.key>`
age +args:
  nix run .#fleet -- age {{args}}

# Compare sops.secrets declarations vs secrets/*.yaml — `just secrets-audit` or `--host x`
secrets-audit *args:
  nix run .#fleet -- secrets audit {{args}}

# Re-encrypt secrets after .sops.yaml recipient change — `just sops-rekey` / `--host x` / `--dry-run`
sops-rekey *args:
  nix run .#fleet -- sops rekey {{args}}

# Print age key rotation checklist
sops-rotate-hint:
  nix run .#fleet -- sops rotate-hint

############################################################################
# meta
############################################################################


# Refresh inventory tooling from fleet-kit:
#   1) regenerate this Justfile (not Justfile.local)
#   2) relink skills/* and .claude/skills
#   3) update flake input fleetkit (path/github pin)
up:
  nix run --refresh .#fleet -- justfile render --output Justfile
  nix run --refresh .#fleet -- inventory skills-link
  nix flake update fleetkit

# Symlink skills/* -> kit skills and .claude/skills -> ./skills (also part of `up`)
skills-link:
  nix run .#fleet -- inventory skills-link

# Optional private recipes (darwin-build, …). Missing file is ignored.
import? "Justfile.local"
"""


def cmd_justfile_render(args, _config):
    if args.output == "-":
        print(JUSTFILE_TEMPLATE, end="")
        return
    Path(args.output).write_text(JUSTFILE_TEMPLATE)
    print(f"wrote {args.output}")
