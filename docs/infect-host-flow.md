# NixOS-Infect Host Flow

This document describes the low-memory VPS install path based on
`nixos-infect`.

Use this flow when a provider machine can boot Debian or Ubuntu and SSH works,
but one of the safer install paths is impractical:

- `nixos-anywhere` kexec runs out of memory.
- The provider does not offer VNC or serial console access.
- Raw image `dd` repeatedly fails in NixOS Stage 1 and is hard to debug.

Do not use this flow on machines that contain data you need to keep. It replaces
the operating system and is intended for newly provisioned or easily reinstalled
hosts.

## Standard Command

Run from the private inventory:

```shell
cd ~/deploy/fleet-private
just infect example-host root@203.0.113.10 builder
```

If the current provider SSH port is not 22:

```shell
nix run .#fleet -- infect example-host root@203.0.113.10 \
  --builder builder \
  --current-port 2222
```

The default full flow is synchronous:

```text
probe -> render-config -> upload-config -> run-infect -> install-secrets
-> reboot -> wait-ssh -> deploy-remote -> health-check
```

The command asks for destructive confirmation unless `--yes` is passed.

## Host Requirements

In the private inventory, infect hosts should be normal deployed NixOS hosts,
not image hosts:

```nix
example-host = {
  image = false;
  path = ./example-host;

  deployment = {
    targetHost = "203.0.113.10";
    targetPort = 2234;
    targetUser = "root";
    buildOnTarget = false;
    tags = ["proxy" "kvm"];
  };
};
```

The host configuration should import the normal KVM profile and avoid raw-image
`disko` root configuration. After infect succeeds, the final root filesystem is
the provider OS root partition by UUID. Full services are applied by
`deploy-remote` after the first NixOS boot.

The builder root public key must be included in `sshAuthorizedKeys`, so the
builder can push the system closure during `deploy-remote`.

## Stages And Recovery

`fleet infect` stores state under `/root/fleet-infect` on the target. This
directory contains `probe.json`, rendered NixOS config files, `infect.log`, and
`*.done` stage markers.

| Stage | Mutates target | Purpose | Resume from here when |
| --- | --- | --- | --- |
| `probe` | Yes, writes state dir | Collect root disk, UUID, boot mode, network, modules, memory | Provider OS was reinstalled or facts changed |
| `render-config` | Yes, writes rendered files | Generate minimal `/etc/nixos` config from probe and flake host config | Probe succeeded but config generation/upload needs repeating |
| `upload-config` | Yes | Copy rendered config to `/etc/nixos` | Rendered config exists but `/etc/nixos` was not updated |
| `run-infect` | Yes, destructive | Download, patch, and run `nixos-infect` with `NO_REBOOT=1` | Infect failed after config upload |
| `install-secrets` | Yes | Install `/etc/sops/age/key.txt` and preserve it through lustrate | Infect succeeded before reboot but secrets were not installed |
| `reboot` | Yes | Reboot into NixOS | Everything is staged and only reboot is left |
| `wait-ssh` | No | Wait for target NixOS SSH port | Reboot happened but command was interrupted |
| `deploy-remote` | Yes | Sync Mac worktree to builder, deploy full fleet config | Minimal NixOS booted but full deploy failed |
| `health-check` | No | Verify SSH, current system, failed units, sshd, fail2ban | Deploy succeeded and final verification is needed |

Examples:

```shell
nix run .#fleet -- infect example-host root@203.0.113.10 --builder builder \
  --stage run-infect

nix run .#fleet -- infect example-host root@203.0.113.10 --builder builder \
  --stage install-secrets

nix run .#fleet -- infect example-host root@203.0.113.10 --builder builder \
  --stage wait-ssh --no-deploy

nix run .#fleet -- infect example-host root@203.0.113.10 --builder builder \
  --stage deploy-remote
```

To stop before a risky boundary:

```shell
nix run .#fleet -- infect example-host root@203.0.113.10 --builder builder \
  --stop-after upload-config
```

For a non-mutating preview:

```shell
nix run .#fleet -- infect example-host root@203.0.113.10 --builder builder \
  --dry-run
```

## Logs

Main logs are printed by the local command. The target also keeps:

```text
/root/fleet-infect/probe.json
/root/fleet-infect/configuration.nix
/root/fleet-infect/hardware-configuration.nix
/root/fleet-infect/infect.log
```

If the provider OS is reinstalled, start from `probe` again. If the machine is
already on minimal NixOS, resume from `wait-ssh` or `deploy-remote`.
