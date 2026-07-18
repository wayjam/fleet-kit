"""`fleet justfile render` — emit the Justfile template (source of truth).

The generated Justfile in fleet-inventory is produced by `just up`, which runs
`fleet justfile render --output Justfile`.
"""

from pathlib import Path

JUSTFILE_TEMPLATE = """# Fleet Justfile shortcuts.
#
# Recipes keep only required positional arguments and pass optional flags through
# to the Python CLI. Use normal fleet flags after the required args:
#   just image panstar-hks --builder builder --no-kvm
#   just image panstar-hks --builder builder --no-kvm --retry 1
#   just deploy panstar-hks --builder builder --retry 1
#   just install panstar-hks --ssh-target root@1.2.3.4:22 --kexec-syscall
#
# For full options:
#   just image <host> --help
#   nix run .#fleet -- image --help

default:
  @just --list

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

# Deploy to a host (stages: sync→lock→apply) — `just deploy <target> [fleet flags...]`
deploy target *args:
  nix run .#fleet -- deploy {{target}} {{args}}

# Deploy to all Colmena hosts (stages: sync→lock→apply) — `just deploy-all [fleet flags...]`
deploy-all *args:
  nix run .#fleet -- deploy-all {{args}}

# Build a disko image (stages: sync→remote-build→verify) — `just image <host> [fleet flags...]`
image host *args:
  nix run .#fleet -- image {{host}} {{args}}

# Download remote-built disko image via SCP — `just download-image <host> [fleet flags...]`
download-image host *args:
  nix run .#fleet -- download-image {{host}} {{args}}

# Convert Debian/Ubuntu → NixOS (stages: probe→render→upload→infect→secrets→reboot→wait→deploy→health)
infect host *args:
  nix run .#fleet -- infect {{host}} {{args}}

# Fresh NixOS install via nixos-anywhere (stages: install→verify) — `just install <host> [fleet flags...]`
install host *args:
  nix run .#fleet -- install {{host}} {{args}}

# Switch a system-manager LXC or existing Linux host — `just lxc-switch <host>`
lxc-switch host:
  nix run .#fleet -- lxc-switch {{host}}

# Print allowed TCP & UDP firewall ports — `just ports <host>`
ports host:
  nix run .#fleet -- ports {{host}}

# Show client proxy/VPN profiles — `just profile <host> [fleet flags...]`
profile host *args:
  nix run .#fleet -- profile {{host}} {{args}}

# Manage remote builder jobs — `just jobs list|status|log|cancel|cleanup --builder <x> [args...]`
jobs *args:
  nix run .#fleet -- jobs {{args}}

# Generate secrets — `just secret uuid | password | hex | randstr | age | age-file <n> | wireguard | ssh <n> | xray-reality | proxy`
secret +args:
  nix run .#fleet -- secret {{args}}

# Read and edit encrypted host secrets — `just age list <host>`, `just age read <host.key>`
age +args:
  nix run .#fleet -- age {{args}}

# Regenerate this Justfile from the fleet template (source of truth).
up:
  nix run --refresh .#fleet -- justfile render --output Justfile
"""


def cmd_justfile_render(args, _config):
    if args.output == "-":
        print(JUSTFILE_TEMPLATE, end="")
        return
    Path(args.output).write_text(JUSTFILE_TEMPLATE)
    print(f"wrote {args.output}")
