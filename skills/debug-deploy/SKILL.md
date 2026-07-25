---
name: debug-deploy
description: >-
  Debug fleet deploy/sync/lock/apply failures against a remote builder or
  colmena apply errors. Use when deploy fails, flake lock override mismatches,
  path fleet-config missing on builder, stale fleet CLI, rsync/tar sync issues.
---

# Debug deploy

## When to use

- `just deploy` / `fleet deploy` stage sync|lock|apply fails
- Builder cannot find inputs (`dotfiles` vs `fleetkit`, missing path)
- Suspect stale `nix run .#fleet` after kit edits

## Prerequisites

- CWD = **private inventory**
- Note the failing **stage** and **full error snippet**

## Decision tree

### 0. Stale path lock (CLI/modules old)

If kit was edited but private lock was not updated:

```shell
nix flake update fleetkit
```

`fleet` also warns when the local path kit tree is newer than `flake.lock`
(`FLEET_SKIP_STALE_CHECK=1` to silence).

### 1. Inventory / layout

```shell
just inventory-doctor
just doctor
```

Check especially:

- `repos.inventory_name` == directory name (`fleet-private`, not old `fleet-inventory`)
- `repos.public_name` sibling exists when fleetkit is a **path** input
- flake uses `fleetkit`, not legacy `dotfiles`

### 2. Sync plan (no transfer)

```shell
just sync --dry-run --builder default
# or: nix run .#fleet -- sync --dry-run --builder default
```

Expect log lines like:

```text
fleet sync: fleetkit_mode=path|remote sync_method=rsync|tar repos=[...]
```

| mode | meaning |
|---|---|
| `path` | sync inventory **and** kit; lock overrides `fleetkit` to remote path |
| `remote` | sync inventory only; builder fetches kit from lock |

If you still see **only** old `tar` with **no** `fleet sync:` line → running **stale fleet**; update lock (step 0).

### 3. Builder health

```shell
just doctor builder
# or just builder-ping default
```

SSH, remote nix, rsync presence, disk.

### 4. Classic error signatures

| Error | Likely cause | Fix |
|---|---|---|
| `override-input fleetkit` does not match any input | Remote tree is **old inventory** (`dotfiles` only) or wrong `inventory_name` | Fix `fleet.toml` `inventory_name`; re-sync |
| `path '//Users/.../fleet-config' does not exist` | Builder evaluating host path to laptop absolute path | Ensure synced inventory uses `fleetkit` + override/path on builder |
| Stage sync SSH 255 | Network/SSH | Retry; check `fleet.toml` builder host/port/key |
| Module option missing after kit change | Stale lock | `nix flake update fleetkit` |

Details: [docs/host-troubleshooting.md](../../docs/host-troubleshooting.md)

### 5. Config diff (optional)

```shell
just diff <host>
```

Runs `colmena apply dry-activate` (no switch). Needs eval/SSH depending on host settings.

## Verify

- [ ] `just sync --dry-run` shows expected mode + repos
- [ ] `just doctor` has no FAIL
- [ ] Deploy stage gets past the previously failing stage

## Not this skill

- Authoring a new host from scratch → `add-host`
- Pure NixOS module design without deploy → edit `fleet-kit` modules + docs
