# AGENTS.md — fleet-kit

Public Nix modules, `fleet` CLI, docs, and a private-inventory template for multi-host fleets.

## What this is / is not

| Is | Is not |
|---|---|
| Reusable `nixosModules` / `systemManagerModules` / `darwinModules` | Real host inventory, IPs, domains |
| `fleet` CLI (deploy, infect, image, secrets, …) | Encrypted or plaintext secrets |
| Docs under `docs/` + task skills under `skills/` | Personal home-manager configs (those stay private) |

Real machines live in a **private inventory** (see `templates/fleet-inventory`, `fleet inventory init`).

## Language

- This repo (AGENTS, skills, public docs): **English**
- Private inventory local notes may be Chinese; do not copy real inventory data into this repo

## Layout (short)

```text
modules/     # nixos, shared, darwin
tools/fleet/ # Python CLI
lib/         # host-inventory helpers
docs/        # human-oriented long-form docs
skills/      # agent task playbooks (not a second docs tree)
templates/fleet-inventory/
examples/hosts/
```

## Hard rules

1. **No real secrets, IPs, or customer hostnames** in this repo.
2. Prefer extending modules/CLI here over duplicating logic in private inventories.
3. Long procedures live in `docs/`; skills only checklist + commands + links.
4. After changing `tools/fleet`, private inventories must `nix flake update fleetkit` (path inputs pin narHash).
5. Do not invent new just entrypoints that bypass `fleet` without updating `tools/fleet/justfile.py`.

## Task → skill routing

| Intent | Skill | Details (docs) |
|---|---|---|
| Add a host (proxy / image / …) | [`skills/add-host`](./skills/add-host/SKILL.md) | [`docs/setup-host.md`](./docs/setup-host.md) |
| Deploy/lock/sync/builder failures | [`skills/debug-deploy`](./skills/debug-deploy/SKILL.md) | [`docs/host-troubleshooting.md`](./docs/host-troubleshooting.md) |
| Infect existing Linux | (follow docs; skill optional later) | [`docs/infect-host-flow.md`](./docs/infect-host-flow.md) |
| Raw disk image / dd | (docs) | [`docs/image-host-checklist.md`](./docs/image-host-checklist.md) |
| Just recipes reference | — | [`docs/just-recipes.md`](./docs/just-recipes.md) |

Before non-trivial work: **Read the matching skill** when one exists.

## Common commands

```shell
nix run .#fleet -- --help
nix run .#fleet -- inventory init ../my-private --git
nix develop
nix flake show
```

From a **private inventory** (after `nix flake update fleetkit`):

```shell
just inventory-list
just inventory-add-host <name> --target-host <ip>
just inventory-doctor
just doctor
just sync --dry-run --builder default
just deploy <host> --builder default
```

## Skills layout for agents

Canonical playbooks: `skills/<name>/SKILL.md`.

Private inventories should symlink:

```text
skills/add-host      -> ../fleet-kit/skills/add-host
skills/debug-deploy  -> ../fleet-kit/skills/debug-deploy
.claude/skills       -> ../skills
```

Recreate with `just skills-link` (inventory) or `fleet inventory skills-link`.

## Verify before finishing

```shell
python3 -m py_compile tools/fleet/*.py
nix flake show
# if you touched modules used by examples/templates, say so in the PR/commit body
```
