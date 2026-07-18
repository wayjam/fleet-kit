# Disk Image Host Checklist

This document describes the checks to run before adding a host that will be
installed by building a raw disk image and writing it to the provider disk with
`dd`.

The goal is to avoid image boot failures caused by missing initrd storage
drivers, wrong disk names, missing first-boot secrets, or mismatched firmware
boot modes.

## When To Use This Flow

Use this checklist when a provider does not support `nixos-anywhere`, when the
machine must be installed by rescue mode, or when the normal install path is to:

```shell
just image-remote-no-kvm example-host builder
zstd -dc main.raw.zst | dd of=/dev/sda bs=16M status=progress conv=fsync
```

For common amd64 KVM VPS hosts where a generic takeover image is enough, prefer
the reusable `bootstrap-vps` image:

```shell
fleet image bootstrap-vps --builder builder
zstd -dc main.raw.zst | dd of=/dev/vda bs=16M status=progress conv=fsync
ssh -p 2234 root@NEW_IP
fleet deploy real-host --builder builder
```

For ARM VPS hosts, use the ARM variant:

```shell
fleet image bootstrap-vps-arm64 --system aarch64-linux --builder builder
```

The `dd` target is the whole target disk as seen by the rescue system, commonly
`/dev/vda`, `/dev/sda`, or `/dev/nvme0n1`. The final deploy does not repartition
the disk; it applies the real host's NixOS configuration on top of the
bootstrap-vps disk layout.

Run the hardware discovery commands on the provider's original OS, Debian rescue
system, or any temporary Linux image that can boot successfully on the target
machine.

If the provider does not offer VNC or serial console access and repeated raw
image attempts fail in Stage 1, prefer the
[nixos-infect flow](./infect-host-flow.md) from the provider's Debian or Ubuntu
image. It preserves the provider's working disk and boot layout, then switches
to the full fleet configuration after the first NixOS boot.

## 1. Collect Hardware Information

Install the basic discovery tools on Debian or a rescue system:

```shell
apt update
apt install -y pciutils usbutils initramfs-tools
```

Collect the host facts:

```shell
uname -a
lsblk -o NAME,MODEL,TRAN,TYPE,SIZE,FSTYPE,LABEL,PARTLABEL,MOUNTPOINTS
findmnt /
lspci -nnk
lsmod | sort
dmesg -T | egrep -i 'virtio|scsi|sata|ahci|ata|nvme|xen|hyper-v|hv_|vmware|mpt|megaraid|disk|block|raid|hpsa|aacraid|isci|sym53|qemu|kvm' | tail -240
```

Map block devices to kernel drivers:

```shell
for d in /sys/block/sd* /sys/block/vd* /sys/block/nvme*; do
  [ -e "$d" ] || continue
  echo "### $(basename "$d")"
  readlink -f "$d/device/driver" 2>/dev/null || true
  readlink -f "$d/device" 2>/dev/null || true
done

rootdev=$(findmnt -n -o SOURCE /)
echo "root=$rootdev"
udevadm info --query=all --name "$rootdev" 2>/dev/null \
  | egrep 'ID_BUS|ID_MODEL|ID_PATH|ID_PART_TABLE|DEVPATH|DEVNAME|MAJOR|MINOR|ID_PART_ENTRY' || true
```

If the temporary OS uses initramfs, inspect which storage modules it includes:

```shell
lsinitramfs /boot/initrd.img-$(uname -r) 2>/dev/null \
  | egrep '/(virtio|ata|ahci|sd_mod|scsi|nvme|xhci|mpt|megaraid|hv_|xen|sr_mod|pata|sym53|aacraid|hpsa|uas|usb-storage).*\.ko' \
  | sed -n '1,200p'
```

Save this output in the private inventory notes or ticket for the host. It is
the evidence used to choose `boot.initrd` modules.

## 2. Identify The Storage Driver

Use `lspci -nnk`, `/sys/block/.../driver`, and `dmesg` together. The important
line is usually `Kernel driver in use`.

Common mappings:

| Provider hardware | Linux clue | NixOS initrd modules |
| --- | --- | --- |
| Virtio block | `Virtio block device`, disk is usually `/dev/vda` | `virtio_pci`, `virtio_blk` |
| Virtio SCSI | `Virtio SCSI`, disk may still be `/dev/sda` | `virtio_pci`, `virtio_scsi`, `sd_mod` |
| AHCI/SATA | `SATA controller ... AHCI`, disk is usually `/dev/sda` | `ahci`, `sd_mod` |
| ATA PIIX/legacy IDE | `PIIX`, `ata_piix` | `ata_piix`, `sd_mod` |
| NVMe | `Non-Volatile memory controller`, disk is `/dev/nvme0n1` | `nvme` |
| VMware paravirtual SCSI | `VMware PVSCSI`, `vmw_pvscsi` | `vmw_pvscsi`, `sd_mod` |
| Hyper-V SCSI | `Microsoft Hyper-V`, `hv_storvsc` | `hv_vmbus`, `hv_storvsc`, `sd_mod` |
| Xen block | `xen-blkfront`, disk may be `/dev/xvda` | `xen-blkfront` |
| MegaRAID | `megaraid_sas` | `megaraid_sas`, `sd_mod` |
| LSI/MPT SAS | `mpt3sas` or `mptsas` | `mpt3sas`, `sd_mod` |

If the temporary OS shows `QEMU HARDDISK` as `/dev/sda` but the sysfs path
contains `virtio.../scsi`, treat it as Virtio SCSI, not plain SATA.

## 3. Configure NixOS Initrd

Put the broad storage drivers in `availableKernelModules` so they are copied
into the initrd:

```nix
boot.initrd.availableKernelModules = [
  "virtio_pci"
  "virtio_blk"
  "virtio_scsi"
  "nvme"
  "sd_mod"
  "ahci"
  "ata_piix"
  "xhci_pci"
];
```

For providers that fail in Stage 1 while waiting for the root filesystem, force
the exact storage path to load early with `kernelModules`:

```nix
boot.initrd.kernelModules = [
  "virtio_pci"
  "virtio_scsi"
  "sd_mod"
];
```

Use `kernelModules` when the console shows:

```text
<<< NixOS Stage 1 >>>
waiting for device /dev/disk/by-partlabel/disk-main-NIXROOT to appear...
Timed out waiting for device ...
mount: ... failed: No such file or directory
```

That error happens before Stage 2 starts. It is not a sops, systemd service, or
application problem. It means the initrd did not create the expected block
device.

## 4. Configure Disko For Images

For raw image hosts, import disko and set a stable partition label:

```nix
imports = [
  inputs.disko.nixosModules.disko
  inputs.sops-nix.nixosModules.sops
  inputs.fleetkit.nixosModules.profiles-kvm-server
];

disko = {
  enableConfig = true;
  devices.disk.main = {
    device = "/dev/sda";
    type = "disk";
    imageSize = "4G";
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

The disk name in `disko.devices.disk.main.device` must match the whole target
disk used by `dd`, such as `/dev/sda`, `/dev/vda`, or `/dev/nvme0n1`.

The boot process mounts root by the partition label generated by disko:

```text
/dev/disk/by-partlabel/disk-main-NIXROOT
```

If Stage 1 cannot find that path, check initrd storage drivers first.

## 5. Configure First-Boot Secrets

Image hosts that need secrets on first boot should use an age key injected into
the image after formatting:

```nix
my.secrets.sopsAgeKey.enable = true;
```

The fleet image builder copies the private inventory's local node age key into:

```text
/etc/sops/age/key.txt
```

Keep the private key under the private inventory's `local/` directory. Do not
track it in git. Encrypt host secret files to both the operator age key and the
node age recipient in `.sops.yaml`.

Verify before building:

```shell
SOPS_AGE_KEY_FILE=local/node-age.txt sops -d secrets/example-host.yaml
nix eval .#nixosConfigurations.example-host.config.sops.age.keyFile --raw
nix eval .#nixosConfigurations.example-host.config.sops.age.sshKeyPaths --json
```

Expected values for image-first-boot hosts:

```text
/etc/sops/age/key.txt
[]
```

Disabling SSH host-key fallback avoids first-boot failures where sops tries to
use `/etc/ssh/ssh_host_*_key` before those keys exist.

## 6. Configure Disk Expansion

Raw images should usually stay small, such as `4G`, and expand after first boot.
For normal VPS nodes, grow root partition 2:

```nix
my.server.diskExpansion.enable = true;
```

The default mode is:

```nix
my.server.diskExpansion.mode = "grow-root";
```

It runs once and expands:

```text
partition 2 -> rest of disk
ext4 root filesystem -> new partition size
```

For a separate data partition instead:

```nix
my.server.diskExpansion = {
  enable = true;
  mode = "data-partition";

  dataPartition = {
    number = 3;
    label = "DATA";
    mountPoint = "/data";
  };
};
```

Use `grow-root` unless the host explicitly needs system/data separation.

## 7. Select Cache Profile

Choose binary cache profile by host location:

```nix
my.nixCore.cacheProfile = "china";  # China mainland VPS
my.nixCore.cacheProfile = "global"; # default, overseas VPS
```

China profile tries the configured mirror first, then falls back to
`cache.nixos.org`. Global profile only uses the official cache.

## 8. Build And Inspect The Image

Build on the configured remote builder:

```shell
just image-remote-no-kvm example-host builder
```

If the command reports an error after:

```text
installation finished!
reboot: Power down
```

check the wrapper script first. The raw image may still have been produced.

On the builder, inspect the image:

```shell
fdisk -l /root/disko-example-host/main.raw
```

For a disko layout with 1 MiB BIOS boot and a root partition starting at sector
4096, the root filesystem starts at offset `4096 * 512 = 2097152`:

```shell
mkdir -p /mnt/image-root
mount -o ro,loop,offset=2097152 /root/disko-example-host/main.raw /mnt/image-root
ls -l /mnt/image-root/etc/sops/age/key.txt
readlink /mnt/image-root/nix/var/nix/profiles/system
umount /mnt/image-root
```

If loop mounting is unavailable, use `debugfs` against a loop device created at
the partition offset:

```shell
loop=$(losetup --find --read-only --show -o 2097152 /root/disko-example-host/main.raw)
debugfs -R 'ls /etc/sops/age' "$loop"
debugfs -R 'cat /nix/var/nix/profiles/system/init' "$loop" | sed -n '1,80p'
losetup -d "$loop"
```

## 9. Write The Image

Write to the whole disk, never to a partition:

```shell
zstd -dc main.raw.zst | dd of=/dev/sda bs=16M status=progress conv=fsync
```

Examples:

```shell
dd of=/dev/sda      # SATA, SCSI, Virtio SCSI
dd of=/dev/vda      # Virtio block
dd of=/dev/nvme0n1  # NVMe
```

After `dd`, reboot from disk.

## 10. Boot Failure Triage

Stage 1 cannot find root:

```text
waiting for device /dev/disk/by-partlabel/disk-main-NIXROOT to appear
```

Action:

- Reboot the temporary OS.
- Re-run `lspci -nnk`, `/sys/block` driver mapping, and `dmesg`.
- Add the storage driver to `boot.initrd.availableKernelModules`.
- If still failing, also add the exact driver stack to
  `boot.initrd.kernelModules`.

Stage 2 kernel panic with:

```text
Kernel panic - not syncing: Attempted to kill init!
```

Action:

- Find earlier console lines around `running activation script...`.
- Check sops key injection and sops manifest paths.
- Confirm `/etc/sops/age/key.txt` exists in the image.
- Confirm `sops.age.sshKeyPaths` and `sops.gnupg.sshKeyPaths` are empty for
  node-age-key image hosts.

SSH port is open but closes immediately:

- Confirm the machine actually booted the expected OS.
- Providers may reinstall Debian with SSH on port `22`, while NixOS is expected
  on `2234`.
- Test both:

  ```shell
  nc -vz -w 5 example.com 22
  nc -vz -w 5 example.com 2234
  ssh -p 22 root@example.com 'echo ok'
  ssh -p 2234 root@example.com 'echo ok'
  ```

## Minimal Image Host Checklist

Before building:

- Initial SSH or rescue access works.
- `lsblk` confirms the whole disk name.
- `lspci -nnk` identifies the storage controller and `Kernel driver in use`.
- `boot.initrd.availableKernelModules` includes the storage driver.
- Provider-sensitive storage drivers are also in `boot.initrd.kernelModules`.
- `disko.devices.disk.main.device` matches the target whole disk.
- `imageSize` is large enough for the system closure.
- `my.secrets.sopsAgeKey.enable = true` for first-boot secrets.
- `local/node-age.txt` exists in the private inventory.
- Host secrets decrypt with `SOPS_AGE_KEY_FILE=local/node-age.txt`.
- `my.server.diskExpansion.enable = true` when small images should use the
  whole target disk after first boot.
- The image derivation evaluates:

  ```shell
  nix eval .#packages.x86_64-linux.example-host.drvPath --raw
  ```
