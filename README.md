# fleet-kit

Public reusable Nix modules, `fleet` CLI, inventory helpers, docs, and a
private-inventory template for multi-host NixOS / LXC fleets (and optional
nix-darwin system modules).

This repository is a **library**. Real hosts, IPs, domains, secrets, and
personal home-manager config belong in a **private** inventory repo.

Consumers should depend on this flake as input **`fleetkit`**:

```nix
{
  inputs.fleetkit.url = "github:YOUR_ORG/fleet-kit"; # or path:../fleet-kit
}
```

## Layout

```text
fleet-kit/
  flake.nix                 # modules, lib, packages.fleet, templates
  modules/                  # nixos / shared / darwin / system-manager pieces
  lib/host-inventory.nix    # helpers for private inventory flakes
  tools/fleet/              # fleet CLI
  templates/fleet-inventory # skeleton private inventory
  examples/hosts/           # identity-free bootstrap / example hosts
  docs/                     # operational documentation
  vars.example.nix          # placeholder identity (do not put real secrets here)
```

## What this provides

- `nixosModules.*` — server profiles, proxy, vpn, web, monitoring, …
- `systemManagerModules.*` — LXC / non-NixOS hosts
- `darwinModules.default` — nix-darwin system modules (no personal home)
- `lib.hostInventory` — Colmena / private-repo output helpers
- `packages.fleet` / `apps.fleet` — deploy/infect/image/secret tooling
- `templates.fleet-inventory` — start a private inventory

There are **no** personal `darwinConfigurations` or real host inventories in this repo.

## Optional China mirrors

Defaults are **global / off** so overseas hosts are not forced through CN mirrors.

| What | Option | Default |
|---|---|---|
| Nix binary cache | `my.nixCore.cacheProfile = "china"` \| `"global"` | `"global"` |
| Homebrew bottles/API (darwin) | `my.homebrew.chinaMirror.enable = true` | `false` |

Example on a China-based host:

```nix
{
  my.nixCore.cacheProfile = "china";
  my.homebrew.chinaMirror.enable = true; # darwin only
}
```

## Private inventory

Quick scaffold (from a parent directory such as `~/deploy`):

```shell
# next to fleet-kit checkout
nix run path:./fleet-kit#fleet -- inventory init fleet-private

# options
nix run path:./fleet-kit#fleet -- inventory init my-inv \
  --fleetkit-url 'path:../fleet-kit' \
  --name my-inv \
  --git \
  --lock
```

Also available via flake template / copy:

```shell
nix flake new -t path:./fleet-kit#fleet-inventory fleet-private
# or
cp -R templates/fleet-inventory ../my-fleet-private
```

Point private `inputs.fleetkit` at this repo (name is always **`fleetkit`**). Three URL forms are supported:

```nix
# absolute path — single fixed machine
fleetkit.url = "path:/Users/you/deploy/fleet-kit";

# relative path — sibling directories (template default)
fleetkit.url = "path:../fleet-kit";

# GitHub / Git — multi-machine / CI after publish
fleetkit.url = "github:YOUR_ORG/fleet-kit";
```

Then register real hosts and keep secrets only in the private repo.

See `docs/README.md` and `templates/fleet-inventory/README.md` for details.

## Dev shell

```shell
nix develop
nix run .#fleet -- --help
```

## Inventory & ops CLI (highlights)

```shell
# scaffold private inventory
nix run .#fleet -- inventory init ../fleet-private --git

# inside a private inventory:
nix run .#fleet -- inventory list
nix run .#fleet -- inventory add-host my-vps --target-host 1.2.3.4 --kind proxy
nix run .#fleet -- inventory doctor
nix run .#fleet -- doctor              # inventory + lock + builder
nix run .#fleet -- doctor builder
nix run .#fleet -- sync --dry-run --builder default
nix run .#fleet -- secrets audit
nix run .#fleet -- sops rekey --dry-run
nix run .#fleet -- sops rotate-hint
nix run .#fleet -- diff <host>         # colmena dry-activate
```

Path `fleetkit` lock stale warning: if the local kit tree is newer than
`flake.lock`, `fleet` prints a fix hint (`nix flake update fleetkit`).
Skip with `FLEET_SKIP_STALE_CHECK=1`.
