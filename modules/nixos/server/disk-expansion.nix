{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.my.server.diskExpansion;

  effectiveDisk =
    if cfg.disk != null
    then cfg.disk
    else config.disko.devices.disk.main.device or null;

  growRootScript = ''
    set -euo pipefail

    marker=${lib.escapeShellArg cfg.markerFile}
    configured_disk=${lib.escapeShellArg (
      if cfg.disk == null
      then ""
      else cfg.disk
    )}
    root_device=${lib.escapeShellArg cfg.rootDevice}

    if [ ! -e "$root_device" ]; then
      root_device="$(${pkgs.util-linux}/bin/findmnt -n -o SOURCE /)"
    fi

    if [ -n "$configured_disk" ] && [ -b "$configured_disk" ]; then
      disk="$configured_disk"
    else
      disk="/dev/$(${pkgs.util-linux}/bin/lsblk -n -o PKNAME "$root_device" | head -n1 | tr -d '[:space:]')"
    fi

    root_partition_number="$(${pkgs.util-linux}/bin/lsblk -n -o PARTN "$root_device" | head -n1 | tr -d '[:space:]')"
    if [ -z "$root_partition_number" ]; then
      root_partition_number=${toString cfg.rootPartitionNumber}
    fi

    if [ -e "$marker" ]; then
      disk_size="$(${pkgs.util-linux}/bin/blockdev --getsize64 "$disk")"
      root_size="$(${pkgs.util-linux}/bin/blockdev --getsize64 "$root_device")"
      if [ "$root_size" -ge "$((disk_size - 67108864))" ]; then
        echo "disk expansion already completed: $marker"
        exit 0
      fi
      echo "disk expansion marker exists but root partition is still smaller than disk; expanding"
    fi

    mkdir -p "$(dirname "$marker")"

    ${pkgs.gptfdisk}/bin/sgdisk -e "$disk" || true
    if ! growpart_output="$(${pkgs.cloud-utils}/bin/growpart "$disk" "$root_partition_number" 2>&1)"; then
      echo "$growpart_output"
      case "$growpart_output" in
        *NOCHANGE*) ;;
        *) exit 1 ;;
      esac
    fi
    ${pkgs.parted}/bin/partprobe "$disk" || true
    ${pkgs.systemd}/bin/udevadm settle || true
    ${pkgs.e2fsprogs}/bin/resize2fs "$root_device"

    touch "$marker"
  '';

  dataPartitionScript = ''
    set -euo pipefail

    marker=${lib.escapeShellArg cfg.markerFile}
    disk=${lib.escapeShellArg effectiveDisk}
    number=${toString cfg.dataPartition.number}
    label=${lib.escapeShellArg cfg.dataPartition.label}
    mount_point=${lib.escapeShellArg cfg.dataPartition.mountPoint}

    if [ -e "$marker" ]; then
      echo "disk expansion already completed: $marker"
      exit 0
    fi

    mkdir -p "$(dirname "$marker")"

    case "$disk" in
      *[0-9]) part_device="''${disk}p''${number}" ;;
      *) part_device="''${disk}''${number}" ;;
    esac

    ${pkgs.gptfdisk}/bin/sgdisk -e "$disk" || true

    if [ ! -b "$part_device" ]; then
      ${pkgs.gptfdisk}/bin/sgdisk \
        -n "''${number}:0:0" \
        -t "''${number}:8300" \
        -c "''${number}:''${label}" \
        "$disk"
      ${pkgs.util-linux}/bin/partprobe "$disk" || true
      ${pkgs.systemd}/bin/udevadm settle || true
    fi

    if ! ${pkgs.util-linux}/bin/blkid "$part_device" >/dev/null 2>&1; then
      ${pkgs.e2fsprogs}/bin/mkfs.ext4 -F -L "$label" "$part_device"
    fi

    mkdir -p "$mount_point"
    if ! ${pkgs.util-linux}/bin/mountpoint -q "$mount_point"; then
      ${pkgs.util-linux}/bin/mount "$part_device" "$mount_point"
    fi

    touch "$marker"
  '';
in {
  options.my.server.diskExpansion = {
    enable = lib.mkEnableOption "one-shot disk expansion after raw image deployment";

    mode = lib.mkOption {
      type = lib.types.enum ["grow-root" "data-partition"];
      default = "grow-root";
      description = "Whether to grow the root partition or create a separate data partition.";
    };

    disk = lib.mkOption {
      type = with lib.types; nullOr str;
      default = null;
      description = "Whole disk device to expand. Defaults to disko.devices.disk.main.device when available.";
    };

    markerFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/fleet-disk-expansion/done";
      description = "Marker file used to run disk expansion only once.";
    };

    rootPartitionNumber = lib.mkOption {
      type = lib.types.int;
      default = 2;
      description = "Partition number to grow when mode is grow-root.";
    };

    rootDevice = lib.mkOption {
      type = lib.types.str;
      default = "/dev/disk/by-partlabel/disk-main-NIXROOT";
      description = "Filesystem device to resize after growing the root partition.";
    };

    dataPartition = {
      number = lib.mkOption {
        type = lib.types.int;
        default = 3;
        description = "Partition number to create when mode is data-partition.";
      };

      label = lib.mkOption {
        type = lib.types.str;
        default = "DATA";
        description = "Partition label and ext4 filesystem label for the data partition.";
      };

      mountPoint = lib.mkOption {
        type = lib.types.str;
        default = "/data";
        description = "Mount point for the data partition.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = effectiveDisk != null;
        message = "my.server.diskExpansion.disk must be set when no disko main disk is configured.";
      }
    ];

    environment.systemPackages = [
      pkgs.cloud-utils
      pkgs.e2fsprogs
      pkgs.gptfdisk
      pkgs.parted
      pkgs.util-linux
    ];

    fileSystems = lib.mkIf (cfg.mode == "data-partition") {
      ${cfg.dataPartition.mountPoint} = {
        device = "/dev/disk/by-label/${cfg.dataPartition.label}";
        fsType = "ext4";
        options = [
          "nofail"
          "x-systemd.device-timeout=10s"
        ];
      };
    };

    systemd.services.fleet-disk-expansion = {
      description = "Expand disk layout after raw image deployment";
      wantedBy = ["multi-user.target"];
      after = ["local-fs.target"];
      unitConfig.ConditionPathExists = "!/etc/fleet/install-method-infect";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script =
        if cfg.mode == "grow-root"
        then growRootScript
        else dataPartitionScript;
    };
  };
}
