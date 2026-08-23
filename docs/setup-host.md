# New Host Setup

This document describes the standard flow for adding a new host to the private inventory repository, then installing and managing it with
`nixos-anywhere`, disk images, system-manager, and Colmena.

Example host used below:

```text
Host name: jp-proxy-01
IP: 203.0.113.10
Current SSH port: 22
Target NixOS SSH port: 2234
Initial user: root
```

Replace all names, addresses, ports, domains, and service values with real
private inventory values.

## 1. Confirm Initial SSH Access

Password login:

```shell
ssh root@203.0.113.10
```

Key login on port 22:

```shell
ssh -p 22 root@203.0.113.10
```

Key login on a custom provider port:

```shell
ssh -p 12345 root@203.0.113.10
```

Do not continue until initial SSH access works. `nixos-anywhere`, image upload,
and Colmena all depend on this path.

## 2. Create the Host Configuration

Work in the private inventory:

```shell
cd ~/deploy/fleet-private
```

Copy a sanitized host template from the public repository:

```shell
cp -R ../fleet-kit/templates/fleet-inventory/hosts/proxy-example hosts/jp-proxy-01
```

Edit the host file:

```shell
$EDITOR hosts/jp-proxy-01/default.nix
```

Minimal KVM host shape:

```nix
{
  config,
  inputs,
  pkgs,
  ...
}: let
  myvars = import ../../vars {inherit (pkgs) lib;};
in {
  imports = [
    inputs.sops-nix.nixosModules.sops
    inputs.fleetkit.nixosModules.profiles-kvm-server

    # Import optional service modules only when this host uses them.
    inputs.fleetkit.nixosModules.proxy-xray
    inputs.fleetkit.nixosModules.proxy-realm
    inputs.fleetkit.nixosModules.monitoring-komari-agent
    inputs.fleetkit.nixosModules.vpn-wireguard
  ];

  system.stateVersion = "25.05";

  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };
  boot.loader.grub.devices = ["/dev/sda"];

  users.mutableUsers = false;
  users.users = {
    root.openssh.authorizedKeys.keys = myvars.sshAuthorizedKeys;
    admin = {
      isNormalUser = true;
      extraGroups = ["wheel"];
      openssh.authorizedKeys.keys = myvars.sshAuthorizedKeys;
      shell = pkgs.zsh;
    };
  };
  programs.zsh.enable = true;

  my.server.ssh = {
    port = 2234;
    authorizedKeys = myvars.sshAuthorizedKeys;
    authorizedKeyUsers = ["root" "admin"];
  };

  sops.defaultSopsFile = ../../secrets/jp-proxy-01.yaml;
  sops.secrets.xray_uuid = {};
  sops.secrets.xray_reality_private_key = {};
  sops.secrets.xray_xhttp_path = {};
  sops.secrets.xray_ss2022_password = {};
  sops.secrets.komari_agent_token = {};
  sops.secrets.wg_private_key = {};
}
```

Check the real disk name on the host or rescue system:

```shell
lsblk
```

Common disk names are `/dev/vda`, `/dev/sda`, and `/dev/nvme0n1`.

## 3. Enable Optional Services

Enable only the services used by the host.

Xray example:

```nix
my.proxy.xray = {
  enable = true;
  inbounds.vless-reality = {
    type = "vless";
    listenPort = 443;
    uuidFile = config.sops.secrets.xray_uuid.path;
    flow = "xtls-rprx-vision";
    transport = "xhttp";
    xhttp.pathFile = config.sops.secrets.xray_xhttp_path.path;
    reality = {
      enable = true;
      privateKeyFile = config.sops.secrets.xray_reality_private_key.path;
      dest = "www.example.com:443";
      serverNames = ["www.example.com"];
      shortIds = ["0123456789abcdef"];
    };
  };

  inbounds.ss2022 = {
    type = "shadowsocks";
    listenPort = 8443;
    method = "2022-blake3-aes-128-gcm";
    passwordFile = config.sops.secrets.xray_ss2022_password.path;
    network = "tcp,udp";
  };
};
```

Realm forwarding example:

```nix
my.proxy.realm = {
  enable = true;
  forwards.ssh-relay = {
    listenPort = 10022;
    remote = "127.0.0.1:22";
    protocol = "tcp";
  };
};
```

Komari agent example:

```nix
my.monitoring.komariAgent = {
  enable = true;
  endpoint = "https://komari.example.com";
  tokenFile = config.sops.secrets.komari_agent_token.path;
};
```

WireGuard example:

```nix
my.vpn.wireguard = {
  enable = true;
  interfaces.wg0 = {
    ips = ["10.7.0.1/24"];
    listenPort = 51820;
    privateKeyFile = config.sops.secrets.wg_private_key.path;
    peers = [
      {
        publicKey = "peer-public-key";
        allowedIPs = ["10.7.0.2/32"];
        persistentKeepalive = 25;
      }
    ];
  };
};
```

## 4. Add Secrets

Generate secret values with the private inventory helper recipes:

```shell
just secret uuid
just secret xray-reality
just secret password --length 16 --mode ss2022
just secret randstr --prefix /
just secret wireguard
```

Create and edit the encrypted host file:

```shell
sops secrets/jp-proxy-01.yaml
git add secrets/jp-proxy-01.yaml
```

To add a known plaintext token to an existing encrypted host file:

```shell
printf '%s' 'replace-with-token' | just age create jp-proxy-01.komari_agent_token
git add secrets/jp-proxy-01.yaml
```

The `age` helper accepts both key forms:

```shell
just age list jp-proxy-01
just age list jp-proxy-01 key=komari_agent_token
just age list jp-proxy-01.komari_agent_token
just age read jp-proxy-01.komari_agent_token
just age edit jp-proxy-01.komari_agent_token
printf '%s' 'replace-with-token' | just age create jp-proxy-01 key=komari_agent_token
git add secrets/jp-proxy-01.yaml
```

Example encrypted data shape before sops encryption:

```yaml
xray_uuid: generated-uuid
xray_reality_private_key: generated-reality-private-key
xray_xhttp_path: /generated-xhttp-path
xray_ss2022_password: generated-ss2022-password
komari_agent_token: existing-komari-token
wg_private_key: generated-wireguard-private-key
```

If a service needs a separate sops file, keep `defaultSopsFile` for most values
and override only that secret:

```nix
sops.defaultSopsFile = ../../secrets/jp-proxy-01.yaml;

sops.secrets.komari_agent_token = {
  sopsFile = ../../secrets/komari.yaml;
  key = "token";
};
```

Every sops file referenced by a host must exist and be tracked by git. Flakes
evaluate tracked files, not untracked working tree files.

## 5. Register the Host

Edit the private inventory index:

```shell
$EDITOR hosts/default.nix
```

Add the host under `nixos`:

```nix
jp-proxy-01 = {
  path = ./jp-proxy-01;

  deployment = {
    targetHost = "203.0.113.10";
    targetPort = 2234;
    targetUser = "root";
    buildOnTarget = true;
    tags = ["proxy" "kvm" "jp"];
  };
};
```

Notes:

- `targetPort` is the SSH port after NixOS is installed.
- The first `nixos-anywhere` or image upload still uses the current provider
  SSH port.
- On macOS managing Linux hosts, keep `buildOnTarget = true` unless a remote
  builder is configured.
- Import service modules in the host file, not in the inventory index.

## 6. Validate Locally

Run formatting and evaluation checks:

```shell
cd ~/deploy/fleet-private
just fmt
just check
just eval
```

Inspect declared firewall ports:

```shell
just ports-tcp jp-proxy-01
just ports-udp jp-proxy-01
```

## Scenario A: Build an Image, dd It, Then Manage With Colmena

Use this when the provider offers rescue mode and wiping the target disk is
acceptable.

Create one host only. The same host key can be used for image generation,
`nixos-anywhere`, and later Colmena deployment.

Copy the image template:

```shell
cd ~/deploy/fleet-private
cp -R ../fleet-kit/templates/fleet-inventory/hosts/image-example hosts/jp-proxy-01
```

Register the host with `image = true`:

```nix
jp-proxy-01 = {
  image = true;
  path = ./jp-proxy-01;

  deployment = {
    targetHost = "203.0.113.10";
    targetPort = 2234;
    targetUser = "root";
    buildOnTarget = true;
    tags = ["proxy" "image" "jp"];
  };
};
```

Minimal disko image shape:

```nix
imports = [
  inputs.disko.nixosModules.disko
  inputs.fleetkit.nixosModules.profiles-kvm-server
];

disko = {
  enableConfig = true;
  devices.disk.main = {
    device = "/dev/vda";
    type = "disk";
    imageSize = "6G";
    content = {
      type = "gpt";
      partitions = {
        bios_boot = {
          size = "1M";
          type = "EF02";
          priority = 0;
        };
        root = {
          name = "NIXROOT";
          size = "100%";
          content = {
            type = "filesystem";
            format = "ext4";
            mountpoint = "/";
          };
        };
      };
    };
  };
};
```

When `disko.enableConfig = true`, do not also define `fileSystems."/"` for the
same root filesystem. Disko generates it from `mountpoint = "/"`.

Build locally on Linux:

```shell
just image jp-proxy-01
```

Build on a Linux remote builder:

```shell
just image-remote-port jp-proxy-01 2234 root@builder-ip /Users/you/.ssh/id_ed25519
```

If the builder has no `/dev/kvm`, use the script fallback:

```shell
just image-script-remote-port jp-proxy-01 2234 root@builder-ip 768 /root/disko-jp-proxy-01 /Users/you/.ssh/id_ed25519
```

Recommended `imageSize` values:

- `4G`: minimal proxy hosts.
- `6G`: default for most small hosts.
- `8G`: safer when Caddy, extra tools, or more services are included.

## Scenario B: Install Directly With nixos-anywhere

Use this when the host can boot the provider OS or rescue system and SSH is
available. `fleet install` adds target preflight, optional Debian/Ubuntu
`kexec-tools` preparation, secure age-key injection, per-phase resume markers,
local logs/failure probes, and final SSH plus configuration health verification.

Run a non-destructive dry-run first:

```shell
cd ~/deploy/fleet-private
just install jp-proxy-01 \
  --ssh-target root@203.0.113.10:12345 \
  --dry-run
```

For an ARM target, the default build mode is remote and syscall kexec is
enabled automatically. The explicit form is:

```shell
just install orcl-nl-arm \
  --ssh-target root@141.144.197.33:2234 \
  --build-on remote \
  --kexec-syscall \
  --backup-ref 'oci://<boot-volume-backup-or-full-backup-id>' \
  --dry-run
```

Run only the read-only preflight before preparing the target:

```shell
just install jp-proxy-01 \
  --ssh-target root@203.0.113.10:12345 \
  --stop-after preflight
```

Preparation is limited to installing `kexec-tools` on Debian/Ubuntu and does
not erase the disk. The flow then tracks `kexec`, `disko`, and `install` as
separate nixos-anywhere phases; `disko` erases the target disk. A real run must
include the provider backup reference via `--backup-ref`; use `--allow-no-backup`
only to explicitly accept the absence of a recovery point. Review the dry-run
and use `--yes` only for the explicit operation. The original SSH port is
passed with `--ssh-port`, kexec and installer SSH use port 22 by default, and
final NixOS SSH uses the host configuration's port.

When a phase fails, inspect `.fleet/logs/install-<host>/` and resume with the
same backup flag, for example:

```shell
just install orcl-nl-arm \
  --ssh-target root@141.144.197.33:2234 \
  --backup-ref 'oci://<backup-id>' \
  --resume --from-stage install --yes
```

The runner never offers `continue` for a destructive phase. It will only offer
destructive retry with `--retry-destructive`; selecting it first probes the
phase's SSH endpoint, saves fresh failure state, and requires typing the stage
name again before repeating the operation.

For a direct manual invocation without the fleet stage runner:

```shell
nixos-anywhere --flake .#jp-proxy-01 root@203.0.113.10
```

Use the current provider SSH port if it is not 22:

```shell
nixos-anywhere --flake .#jp-proxy-01 -p 12345 root@203.0.113.10
```

After installation, deploy through Colmena on the target NixOS SSH port:

```shell
just deploy jp-proxy-01
```

## Scenario C: Convert Provider Debian With nixos-infect

Use this when the provider can boot Debian or Ubuntu and root SSH works, but
`nixos-anywhere` kexec runs out of memory or raw disk images are too hard to
debug without VNC.

Register the host as a normal deployed host, not an image host:

```nix
jp-proxy-01 = {
  image = false;
  path = ./jp-proxy-01;

  deployment = {
    targetHost = "203.0.113.10";
    targetPort = 2234;
    targetUser = "root";
    buildOnTarget = false;
    tags = ["proxy" "kvm" "jp"];
  };
};
```

Run the full synchronous flow:

```shell
just infect jp-proxy-01 root@203.0.113.10 builder
```

If the provider SSH port is not 22:

```shell
nix run .#fleet -- infect jp-proxy-01 root@203.0.113.10 \
  --builder builder \
  --current-port 2222
```

The command stages minimal NixOS with `nixos-infect`, reboots, waits for the
configured NixOS SSH port, then deploys the full fleet configuration from the
remote builder. Use `--stage` and `--stop-after` to recover from an interrupted
stage instead of restarting from scratch.

See [infect-host-flow.md](./infect-host-flow.md) for the complete stage and
recovery reference.

## Scenario D: Manage a Non-NixOS LXC Host

Use this for LXC or other non-NixOS hosts where replacing the OS is not the
goal.

1. Install Nix on the host.
2. Import `fleetkit.systemManagerModules.lxc-host` in the private inventory.
3. Use system-manager to activate the host profile.

Keep service expectations conservative on LXC. Kernel, firewall, WireGuard,
and systemd behavior may be constrained by the provider.

## Scenario E: NAT or Provider Port Mapping

For NAT hosts, declare internal service ports in Nix and record provider port
mapping in the private host file or private notes.

Example:

```text
Provider public TCP 31022 -> host TCP 22
Provider public TCP 31443 -> host TCP 443
```

Do not put real provider mappings in the public repository.

## After Installation

Deploy a single host:

```shell
just deploy jp-proxy-01
```

Deploy by Colmena tag:

```shell
colmena apply --on @proxy
```

If evaluation uses old module options or a path input does not refresh, see
[host-troubleshooting.md](./host-troubleshooting.md).
