# Just Recipes

This document describes the `Justfile` recipes exposed by a private inventory repository generated from this project.

Run commands from the private inventory root:

```shell
cd ../fleet-private
just --list
```

Pass Fleet flags after the required Just arguments:

```shell
just secret password --length 16 --mode ss2022
just download-image aws-jp1 --output main.raw
```

## Validation And Build

### `just fmt`

Format Nix files.

```shell
just fmt
```

### `just check`

Run flake checks.

```shell
just check
```

### `just eval`

Evaluate the fleet outputs without deploying.

```shell
just eval
```

### `just build <host>`

Build one host system closure locally.

```shell
just build aws-jp1
```

## Deployment And Install

### `just deploy <target>`

Deploy one host or Colmena target selector.

```shell
just deploy aws-jp1
just deploy @proxy
```

### `just deploy-remote <target> [builder]`

Sync the local public and private worktrees to a remote builder, then deploy
from that builder with Colmena. Builder SSH uses an explicit connection timeout
and retries transient rsync/tar transport failures automatically before the
stage runner asks for a manual resume.

```shell
just deploy-remote aws-jp1 builder
```

### `just deploy-all`

Deploy all Colmena hosts.

```shell
just deploy-all
```

### `just install <host> [fleet flags]`

Install a fresh NixOS host with `nixos-anywhere`. The command runs six stages:
read-only `preflight`, non-destructive `prepare-target`, then separately tracked
`kexec`, `disko`, `install`, and post-reboot `verify`. `disko` is the stage that
erases the configured target disk. Each nixos-anywhere phase is logged locally,
and a failed destructive stage is not retried or continued by default.
Use `--dry-run` to print all phase commands without connecting to the target.

For a Debian ARM host currently using SSH port 2234:

```shell
just install orcl-nl-arm \
  --ssh-target root@141.144.197.33:2234 \
  --build-on remote \
  --kexec-syscall \
  --backup-ref 'oci://<boot-volume-backup-or-full-backup-id>' \
  --dry-run
```

After reviewing the dry-run, run preflight only:

```shell
just install orcl-nl-arm \
  --ssh-target root@141.144.197.33:2234 \
  --stop-after preflight
```

Preparation installs only `kexec-tools` on Debian/Ubuntu. The final NixOS SSH
port is taken from the host configuration (`2234` here); kexec and installer SSH
use port `22` via `--post-kexec-ssh-port 22`. Before a real destructive run,
pass the provider backup reference with `--backup-ref` and add `--yes` after
reviewing the dry-run. If no backup exists, `--allow-no-backup` is an explicit
risk acknowledgement. If `disko` or `install` fails, resume from that stage,
for example `--resume --from-stage disko` or `--resume --from-stage install`;
do not restart from `kexec` unless the installer state is known to be gone.
Destructive retry is disabled by default; `--retry-destructive` first probes
the stage's SSH endpoint, saves fresh failure state, and requires typing the
stage name again before repeating the operation.

### `just infect <host> [ssh-target] [builder]`

Convert a provider Debian or Ubuntu host to NixOS with `nixos-infect`, then
deploy the full fleet configuration from the remote builder.

```shell
just infect aws-jp1 root@203.0.113.10 builder
```

If the provider SSH port is not 22, use the underlying fleet command:

```shell
nix run .#fleet -- infect aws-jp1 root@203.0.113.10 \
  --builder builder \
  --current-port 2222
```

Useful recovery flags:

```shell
nix run .#fleet -- infect aws-jp1 root@203.0.113.10 --builder builder --dry-run
nix run .#fleet -- infect aws-jp1 root@203.0.113.10 --builder builder --stage run-infect
nix run .#fleet -- infect aws-jp1 root@203.0.113.10 --builder builder --stage deploy-remote
nix run .#fleet -- infect aws-jp1 root@203.0.113.10 --builder builder --stop-after upload-config
```

Stages are documented in [infect-host-flow.md](./infect-host-flow.md).

## Images

### `just image <host>`

Build a disko image for a host.

```shell
just image aws-jp1
```

### `just image-remote <host> [builder]`

Build a disko image on the configured remote builder.

```shell
just image-remote aws-jp1
just image-remote aws-jp1 builder
```

### `just image-remote-no-kvm <host> [builder]`

Build a disko image on a remote builder without requiring KVM.

```shell
just image-remote-no-kvm aws-jp1
```

### `just image-download <host> [builder] [output]`

Download a remote-built disko image.

```shell
just image-download aws-jp1 output=main.raw
just image-download aws-jp1 builder output=aws-jp1.raw
```

## Builder Checks

### `just builder-ping [builder]`

Check connectivity to the configured remote builder.

```shell
just builder-ping
just builder-ping builder
```

### `just builder-dry-run <host> [builder]`

Dry-run a host build on the configured remote builder.

```shell
just builder-dry-run aws-jp1
just builder-dry-run aws-jp1 builder
```

## Host Introspection

### `just ports-tcp <host>`

Print allowed TCP ports for a host.

```shell
just ports-tcp aws-jp1
```

### `just ports-udp <host>`

Print allowed UDP ports for a host.

```shell
just ports-udp aws-jp1
```

### `just profile <host>`

Show client connection profiles from host config and secrets.

```shell
just profile aws-jp1
```

### `just age <list|read|edit|create> <target> [key=<key>]`

List, read, edit, or create one top-level key in an encrypted host secret file.

```shell
just age list aws-jp1
just age list aws-jp1 key=komari_agent_token
just age list aws-jp1.komari_agent_token
just age read aws-jp1.komari_agent_token
just age edit aws-jp1.komari_agent_token
printf '%s' 'token-value' | just age create aws-jp1 key=komari_agent_token
```

### `just profile-kind <host> <kind>`

Show client connection profiles for one backend kind.

Supported kinds are `xray`, `hy2`, and `wireguard`.

```shell
just profile-kind aws-jp1 xray
just profile-kind aws-jp1 hy2
```

### `just lxc-switch <host>`

Switch a system-manager LXC or existing Linux host.

```shell
just lxc-switch lxc-example
```

## Secrets

### `just secret uuid`

Generate a UUID.

```shell
just secret uuid
```

### `just secret password [flags]`

Generate a random password using the flag-based fleet CLI.

`mode` is `plain` or `ss2022`.

```shell
just secret password
just secret password --length 16 --mode ss2022
```

### `just secret hex [flags]`

Generate random hex.

```shell
just secret hex
just secret hex --bytes 16
```

### `just secret randstr [flags]`

Generate a reusable random hex string. Use `--prefix /` for xHTTP paths.

```shell
just secret randstr
just secret randstr --bytes 16 --prefix /
```

### `just secret xray-shortid [flags]`

Generate an Xray Reality shortId.

```shell
just secret xray-shortid
just secret xray-shortid --bytes 8
```

### `just secret xray-reality`

Generate an Xray Reality keypair.

```shell
just secret xray-reality
```

### `just secret age`

Print an age keypair.

```shell
just secret age
```

### `just secret age-file <name>`

Create a local age key file under `local/keys` when `name` has no slash.

```shell
just secret age-file admin
```

### `just secret wireguard`

Generate a WireGuard keypair.

```shell
just secret wireguard
```

### `just secret ssh <name> [flags]`

Generate an SSH ed25519 keypair under `local/keys` when `name` has no slash.

```shell
just secret ssh admin --comment operator@example.invalid
```

### `just secret proxy`

Generate a proxy secret bundle.

```shell
just secret proxy
```

## Maintenance

### `just up`

Regenerate the private inventory `Justfile` from the fleet template.

```shell
just up
```
