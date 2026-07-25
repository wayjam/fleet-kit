---
name: add-host
description: >-
  Add a NixOS host to a fleet-kit private inventory (proxy or image kind).
  Use when the user wants a new VPS/host, register inventory, scaffold
  hosts/<name>, secrets placeholder, or inventory add-host.
---

# Add host

## When to use

- New machine in a **private inventory** (not inside `fleet-kit` itself)
- User says add host / new VPS / register server

## Prerequisites

- CWD is the **private inventory** root (`flake.nix` + `hosts/` + `fleet.toml`)
- `fleetkit` input works (`nix flake metadata` shows it)
- Prefer current CLI: `nix flake update fleetkit` if kit just changed

## Ask (if missing)

1. **name** — inventory key, e.g. `aws-sg2` (`[a-zA-Z][a-zA-Z0-9_-]*`)
2. **kind** — `proxy` (default) or `image`
3. **targetHost** / **targetPort** / **targetUser** (default port `2234`, user `root`)
4. **tags** — e.g. `proxy`, `kvm`

## Steps

1. Scaffold + register:

   ```shell
   just inventory-add-host <name> --target-host <ip> --kind proxy
   # or:
   nix run .#fleet -- inventory add-host <name> --target-host <ip> --kind proxy
   # richer template copy:
   just inventory-add-host <name> --target-host <ip> --kind proxy --from-template
   ```

2. Edit `hosts/<name>/default.nix`:
   - modules / proxy inbounds / disk device
   - Do **not** paste long proxy theory here — see [docs/setup-host.md](../../docs/setup-host.md)

3. Secrets (if host uses sops):

   ```shell
   sops secrets/<name>.yaml
   git add secrets/<name>.yaml
   ```

4. Verify:

   ```shell
   just eval
   just inventory-doctor
   # optional:
   just secrets-audit --host <name>
   ```

5. Commit inventory changes (private repo only).

## Verify

- [ ] Host appears in `just inventory-list`
- [ ] `hosts/default.nix` has deployment block
- [ ] `just eval` lists the host (or only fails on missing tracked sops file — then create + `git add`)
- [ ] No real secrets committed as plaintext

## Common failures

| Symptom | Action |
|---|---|
| `host already registered` | Pick another name or edit existing host |
| eval fails missing sops file | Create encrypted file, `git add` |
| unknown option from kit module | `nix flake update fleetkit` then retry |
| Deploy issues after add | Use skill `debug-deploy` |

## Not this skill

- Changing public modules → work in `fleet-kit`, then update private lock
- Infect / image pipeline → `docs/infect-host-flow.md` / `docs/image-host-checklist.md`
