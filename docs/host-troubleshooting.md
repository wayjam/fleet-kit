# Host Troubleshooting

This document covers common problems while maintaining the private host
inventory and deploying hosts.

## Changed an Option, but Nix Says It Does Not Exist

Typical error:

```text
error: The option `my.proxy.xray.inbounds' does not exist.
Definition values:
- In `/nix/store/...-source/hosts/image-example':
    {
      vless-reality = {
        ...
```

Common situation:

- `fleet-private/flake.nix` uses the public repo as a local path input:

  ```nix
  inputs.fleetkit.url = "path:/path/to/deploy/fleet-kit";
  ```

- A module option changed in `fleet-kit`.
- The host configuration in the private inventory was updated to the new option.
- `nix build`, `just image-remote-port`, or `just eval` still evaluates the old
  module snapshot.

Cause:

Nix flakes lock path inputs by `narHash`. Even local path inputs are evaluated
through the source snapshot recorded in `flake.lock`.

Check the lock file:

```shell
cd ~/deploy/fleet-private
rg -n '"fleetkit"|narHash|path' flake.lock
```

Refresh the public repo input:

```shell
nix flake update fleetkit
```

Older Nix versions:

```shell
nix flake lock --update-input fleetkit
```

Then re-evaluate:

```shell
nix eval .#nixosConfigurations.image-example.config.my.proxy.xray.inbounds.vless-reality.type
```

Rule of thumb:

- Changes under `fleet-private/hosts/...` usually do not require updating the
  `fleetkit` input.
- Changes under `fleet-kit/modules/...`, `fleet-kit/flake.nix`, or public
  template files used by the flake usually require `nix flake update fleetkit`
  from the private inventory.
- If an error path contains `/nix/store/...-source/...`, verify which flake
  snapshot is being evaluated.

## Host File References an Untracked Secret

Typical error:

```text
error: getting status of '/nix/store/...-source/secrets/jp-proxy-01.yaml': No such file or directory
```

Cause:

Flakes evaluate files tracked by git. A sops file can exist in the working tree
but still be absent from the flake source if it has not been added.

Fix:

```shell
cd ~/deploy/fleet-private
git status --short
git add secrets/jp-proxy-01.yaml
just check
```

Apply the same rule to any secret with an explicit `sopsFile`.

## Disko Option Does Not Exist

Typical error:

```text
error: The option `disko' does not exist
```

Cause:

The host defines `disko = { ... }` but does not import the disko module.

Fix:

```nix
imports = [
  inputs.disko.nixosModules.disko
  inputs.fleetkit.nixosModules.profiles-kvm-server
];
```

## Root Filesystem Is Defined Twice

Typical situation:

- The host has `disko.enableConfig = true`.
- The host also defines `fileSystems."/"` manually.

Cause:

Disko generates `fileSystems."/"` from the partition with `mountpoint = "/"`.
A second manual root filesystem definition can conflict with it.

Fix:

Use one source of truth. For image and disko hosts, prefer the disko-generated
filesystem configuration.

## Duplicate GRUB Devices

Typical error:

```text
You cannot have duplicated devices in mirroredBoots
```

Common cause:

A BIOS/GRUB + GPT disko configuration already defines the boot disk, while the
host also sets:

```nix
boot.loader.grub.devices = ["/dev/vda"];
```

Fix:

Remove the duplicate manual GRUB device setting unless the host has a specific
bootloader reason to keep it.

## Build Fails on macOS With x86_64-linux Required

Typical error:

```text
a 'x86_64-linux' ... is required ... but I am a 'aarch64-darwin'
```

Cause:

The controller machine is macOS, but the target NixOS system or disko image is
`x86_64-linux`.

Options:

- Set `buildOnTarget = true` for normal Colmena deployments.
- Use a Linux remote builder.
- Use `nixos-anywhere` so the target host performs the Linux installation.
- For disk images, build on Linux or use a configured remote builder.

## Temporary Linux Remote Builder

Use this when a Linux VPS, rescue system, or temporary VM should build
`x86_64-linux` artifacts for a macOS controller.

Install multi-user Nix on the builder:

```shell
curl --proto '=https' --tlsv1.2 -L https://nixos.org/nix/install | sh -s -- --daemon
```

Minimal dependencies on small distributions:

```shell
apt-get update
apt-get install -y curl xz-utils sudo
```

Load the Nix environment if needed:

```shell
. /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
```

Verify the builder:

```shell
nix --version
nix eval --impure --expr builtins.currentSystem
```

Expected system:

```text
"x86_64-linux"
```

Recommended `/etc/nix/nix.conf` for a temporary root builder:

```text
experimental-features = nix-command flakes
trusted-users = root
substituters = https://cache.nixos.org https://nix-community.cachix.org
trusted-public-keys = cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY= nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs=
```

Restart the daemon:

```shell
systemctl restart nix-daemon
```

Check KVM:

```shell
test -e /dev/kvm && echo kvm-ok || echo no-kvm
```

For multi-user Nix, build users also need KVM access:

```shell
getent group kvm
sudo -u nixbld1 test -r /dev/kvm -a -w /dev/kvm && echo nixbld-kvm-ok || echo nixbld-no-kvm
```

If needed:

```shell
for user in $(getent passwd | cut -d: -f1 | grep '^nixbld'); do
  usermod -aG kvm "$user"
done
systemctl restart nix-daemon
```

Verify from the private inventory:

```shell
cd ~/deploy/fleet-private
just builder-ping-port 2222 root@203.0.113.10 /Users/you/.ssh/id_ed25519
just builder-dry-run-port image-example 2222 root@203.0.113.10 /Users/you/.ssh/id_ed25519
```

Then build:

```shell
just image-remote-port image-example 2222 root@203.0.113.10 /Users/you/.ssh/id_ed25519
```

## Remote Builder Has Matching Features but Nix Still Finds No Machine

Typical error:

```text
Failed to find a machine for remote build!
required (system, features): (x86_64-linux, [])
1 available machines:
([x86_64-linux], 1, [], [])
```

If the required features match the listed builder, the last line can be
misleading. The local Nix daemon may not be able to SSH into the builder.

Important distinction:

- `nix store info --store ssh-ng://root@203.0.113.10:2222` may use the current
  shell user.
- `nix build --builders ...` may be started by the local Nix daemon.
- The daemon may not inherit `NIX_SSHOPTS`.
- Older Nix versions may not handle `ssh-ng://user@host:port` as expected.
- The daemon may not have access to the same SSH key as the current user.

Check the local Nix version:

```shell
nix --version
```

Test the store URI:

```shell
nix store info --store ssh-ng://root@203.0.113.10:2222
```

Prefer passing an explicit SSH key in the builder recipe:

```shell
cd ~/deploy/fleet-private
just builder-ping-port 2222 root@203.0.113.10 /Users/you/.ssh/id_ed25519
just builder-dry-run-port image-example 2222 root@203.0.113.10 /Users/you/.ssh/id_ed25519
just image-remote-port image-example 2222 root@203.0.113.10 /Users/you/.ssh/id_ed25519
```

Equivalent builder machine spec:

```text
ssh-ng://root@203.0.113.10:2222 x86_64-linux /Users/you/.ssh/id_ed25519 1 1 - -
```

Minimal remote build test:

```shell
nix build --no-link \
  --builders "ssh-ng://root@203.0.113.10:2222 x86_64-linux /Users/you/.ssh/id_ed25519 1 1 - -" \
  --option builders-use-substitutes true \
  --max-jobs 0 \
  --impure --expr '(with import <nixpkgs> { system = "x86_64-linux"; }; runCommand "remote-builder-test" {} "uname -m > $out")'
```

If the log shows building on the remote store, the SSH path and daemon
scheduling are working.

## KVM Feature Is Actually Missing

Typical error:

```text
required (system, features): (x86_64-linux, [kvm])
1 available machines:
([x86_64-linux], 1, [], [])
```

Cause:

`system.build.diskoImages` uses a VM and requires a builder with the `kvm`
feature.

Check the builder:

```shell
ssh -p 2222 root@203.0.113.10 'test -e /dev/kvm && echo kvm-ok || echo no-kvm'
```

If KVM exists, the builder machine spec must include `kvm`:

```text
ssh-ng://root@203.0.113.10:2222 x86_64-linux /Users/you/.ssh/id_ed25519 1 1 kvm -
```

If KVM is not available, use the script fallback:

```shell
just image-script-remote-port image-example 2222 root@203.0.113.10 768 /root/disko-image-example /Users/you/.ssh/id_ed25519
```

This builds `system.build.diskoImagesScript` and runs it on the remote host.
QEMU falls back to TCG, which is slower but does not require KVM.

## Remote Build Fails With Invalid Public Key

Typical error:

```text
error: public key is not valid
```

Cause:

The builder has an invalid `trusted-public-keys` entry in `/etc/nix/nix.conf`.

Check the builder:

```shell
ssh -p 2222 root@203.0.113.10 \
  'nix show-config | grep -E "substituters|trusted-public-keys|trusted-users"'
```

Common valid values:

```text
substituters = https://cache.nixos.org https://nix-community.cachix.org
trusted-public-keys = cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY= nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs=
trusted-users = root
```

Restart the builder daemon after changes:

```shell
systemctl restart nix-daemon
```

## Custom SSH Port Does Not Work With Remote Build

For older Nix versions or daemon-driven builds, use a daemon-visible SSH alias
instead of relying on `NIX_SSHOPTS`.

On macOS, configure root's SSH client:

```shell
sudo mkdir -p /var/root/.ssh
sudo chmod 700 /var/root/.ssh
sudo $EDITOR /var/root/.ssh/config
```

Example:

```sshconfig
Host linux-builder
  HostName 203.0.113.10
  User root
  Port 2222
  StrictHostKeyChecking accept-new
```

If root needs a separate key:

```shell
sudo ssh-keygen -t ed25519 -f /var/root/.ssh/nix-builder -N ''
sudo cat /var/root/.ssh/nix-builder.pub
```

Add the public key to the builder's `/root/.ssh/authorized_keys`, then add:

```sshconfig
  IdentityFile /var/root/.ssh/nix-builder
```

Verify daemon-side SSH:

```shell
sudo ssh linux-builder nix --version
```

Use the alias:

```shell
cd ~/deploy/fleet-private
just image-remote image-example linux-builder
```

## Colmena Cannot Connect After Installation

Check these items in order:

1. The host is reachable on the installed SSH port:

   ```shell
   ssh -p 2234 root@203.0.113.10
   ```

2. `deployment.targetPort` matches `my.server.ssh.port`.
3. The firewall allows the SSH port.
4. The deployed host has the expected authorized keys.
5. NAT provider port mapping, if any, forwards to the internal SSH port.

Inspect declared ports:

```shell
just ports-tcp jp-proxy-01
just ports-udp jp-proxy-01
```

## References

- [Nix manual: Installing a Binary Distribution](https://nixos.org/manual/nix/stable/installation/installing-binary)
- [Nix manual: Multi-User Mode](https://nixos.org/manual/nix/stable/installation/multi-user)
- [nix.dev: Distributed Builds](https://nix.dev/tutorials/nixos/distributed-builds-setup.html)
- [Nix manual: Remote Builds](https://nix.dev/manual/nix/2.18/advanced-topics/distributed-builds)
