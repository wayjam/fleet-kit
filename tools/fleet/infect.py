"""`fleet infect` — multi-stage nixos-infect pipeline.

Stages: probe → render-config → upload-config → run-infect → install-secrets
→ reboot → wait-ssh → deploy-remote → health-check. State markers persist on
the target under REMOTE_INFECT_DIR so stages can resume.

The pipeline is executed through :class:`StageRunner` for unified retry /
resume / interactive failure handling.
"""

import argparse
import base64
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

from builder import apply_builder_overrides, builder_config, remote_nix_expr, ssh_args
from common import capture, die, repo_path
from deploy import cmd_deploy
from known_hosts import clear_local_known_host, remote_clear_known_host_script
from nix import eval_host_json, eval_host_raw, host_deployment
from orchestrator import RunContext, Stage, StageRunner, make_context
from target import (
    normalize_ssh_target,
    target_read_text,
    target_run,
    target_upload_text,
    wait_ssh_down,
    wait_ssh_up,
)


INFECT_STAGES = [
    "pre-clean",
    "probe",
    "render-config",
    "upload-config",
    "run-infect",
    "install-secrets",
    "reboot",
    "wait-ssh",
    "deploy-remote",
    "post-clean",
    "health-check",
]

REMOTE_INFECT_DIR = "/root/fleet-infect"
MIN_INFECT_FREE_MIB = 2500


def key_identity(key):
    parts = str(key).strip().split()
    if len(parts) < 2:
        return str(key).strip()
    return " ".join(parts[:2])


def nix_string(value):
    return json.dumps(str(value))


def nix_list(values):
    return "[ " + " ".join(nix_string(value) for value in values if str(value).strip()) + " ]"


def nix_bool(value):
    return "true" if value else "false"


def target_mark_stage(user, host, port, stage, *, timeout=30):
    marker = f"{REMOTE_INFECT_DIR}/{stage}.done"
    target_run(
        user,
        host,
        port,
        f"mkdir -p {REMOTE_INFECT_DIR}; date -u +%FT%TZ > {shlex.quote(marker)}",
        timeout=timeout,
    )


def identity_path(ctx):
    return ctx.state_dir / "target-identity.json"


def identity_from_probe(probe, user, host, port):
    return {
        "user": user,
        "host": host,
        "port": int(port),
        "root_uuid": probe.get("root_uuid", ""),
        "root_source": probe.get("root_source", ""),
        "disk": probe.get("disk", ""),
        "boot_mode": probe.get("boot_mode", ""),
    }


def save_target_identity(ctx, probe, user, host, port):
    identity_path(ctx).write_text(json.dumps(identity_from_probe(probe, user, host, port), indent=2) + "\n")


def probe_target_identity(user, host, port, args):
    script = r"""
root_source=$(findmnt -n -o SOURCE / | head -n1)
root_real=$(realpath "$root_source" 2>/dev/null || printf '%s' "$root_source")
root_uuid=$(blkid -s UUID -o value "$root_real" 2>/dev/null || true)
disk_name=$(lsblk -n -o PKNAME "$root_real" 2>/dev/null | head -n1 | tr -d '[:space:]')
if [ -n "$disk_name" ]; then disk="/dev/$disk_name"; else disk="$root_real"; fi
if [ -d /sys/firmware/efi ]; then boot_mode=uefi; else boot_mode=bios; fi
printf 'root_source\t%s\nroot_uuid\t%s\ndisk\t%s\nboot_mode\t%s\n' "$root_source" "$root_uuid" "$disk" "$boot_mode"
"""
    probe = {}
    output = target_run(user, host, port, script, timeout=args.timeout, capture_output=True)
    for raw in output.splitlines():
        if "\t" in raw:
            key, value = raw.split("\t", 1)
            probe[key] = value.strip()
    return identity_from_probe(probe, user, host, port)


def identity_mismatch_keys(saved, current, *, compare_port=True):
    keys = ["user", "host", "root_uuid", "disk", "boot_mode"]
    if compare_port:
        keys.insert(2, "port")
    return [key for key in keys if str(saved.get(key, "")) != str(current.get(key, ""))]


def check_resume_identity(ctx, user, host, port, args, *, compare_port=True):
    markers = list(ctx.state_dir.glob("*.done")) + list(ctx.state_dir.glob("*.skip"))
    if not markers:
        return
    path = identity_path(ctx)
    if not path.exists():
        die("existing infect state has no target identity; rerun with --restart after reinstall")
    saved = json.loads(path.read_text())
    current = probe_target_identity(user, host, port, args)
    mismatches = identity_mismatch_keys(saved, current, compare_port=compare_port)
    if mismatches:
        die(f"target identity changed since saved infect state ({', '.join(mismatches)}); rerun with --restart")


def infect_channel(host, args):
    if args.nix_channel:
        return args.nix_channel
    release = eval_host_raw(host, "system.nixos.release", "")
    state_version = eval_host_raw(host, "system.stateVersion", "25.05")
    source = release or state_version
    parts = source.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1][:2].isdigit():
        return f"nixos-{parts[0]}.{parts[1][:2]}"
    return "nixos-25.05"


def detect_initrd_modules(host):
    modules = eval_host_json(host, "boot.initrd.availableKernelModules", [])
    forced = eval_host_json(host, "boot.initrd.kernelModules", [])
    fallback = ["virtio_pci", "virtio_blk", "virtio_scsi", "nvme", "sd_mod", "ahci", "ata_piix", "xhci_pci"]
    merged = []
    for item in [*modules, *forced, *fallback]:
        if item and item not in merged:
            merged.append(item)
    return merged


def build_networking_nix(probe, host_name=None):
    iface = probe.get("iface") or "eth0"
    lines = [
        "networking = {",
        f"  hostName = {nix_string(host_name)};" if host_name else "",
        "  useDHCP = false;",
        f"  interfaces.{nix_string(iface)} = {{",
    ]
    lines = [line for line in lines if line]
    ipv4 = probe.get("ipv4") or []
    ipv6 = probe.get("ipv6") or []
    if ipv4:
        lines.append("    ipv4.addresses = [")
        for item in ipv4:
            address, prefix = item.split("/", 1)
            lines.append(f"      {{ address = {nix_string(address)}; prefixLength = {int(prefix)}; }}")
        lines.append("    ];")
    if ipv6:
        lines.append("    ipv6.addresses = [")
        for item in ipv6:
            address, prefix = item.split("/", 1)
            lines.append(f"      {{ address = {nix_string(address)}; prefixLength = {int(prefix)}; }}")
        lines.append("    ];")
    lines.append("  };")
    if probe.get("gateway4"):
        lines.append(f"  defaultGateway = {nix_string(probe['gateway4'])};")
    if probe.get("gateway6"):
        lines.extend(
            [
                "  defaultGateway6 = {",
                f"    address = {nix_string(probe['gateway6'])};",
                f"    interface = {nix_string(iface)};",
                "  };",
            ]
        )
    nameservers = probe.get("nameservers") or ["1.1.1.1", "8.8.8.8"]
    lines.append(f"  nameservers = {nix_list(nameservers)};")
    lines.append("};")
    return "\n".join(lines)


def render_infect_configs(host, probe, args):
    root_keys = eval_host_json(host, "users.users.root.openssh.authorizedKeys.keys", [])
    admin_keys = eval_host_json(host, "users.users.admin.openssh.authorizedKeys.keys", [])
    ssh_keys = []
    for key in [*root_keys, *admin_keys]:
        if key and key not in ssh_keys:
            ssh_keys.append(key)
    if not ssh_keys:
        die(f"{host} has no root/admin SSH authorized keys")

    target_port = args.target_port or int(host_deployment(host).get("targetPort", 2234))
    state_version = eval_host_raw(host, "system.stateVersion", "25.05")
    kernel_params = eval_host_json(host, "boot.kernelParams", [])
    grub_devices = eval_host_json(host, "boot.loader.grub.devices", [])
    if not grub_devices:
        legacy_grub_device = eval_host_raw(host, "boot.loader.grub.device", "")
        grub_devices = [legacy_grub_device or probe.get("disk") or "/dev/sda"]
    initrd_modules = detect_initrd_modules(host)
    root_device = f"/dev/disk/by-uuid/{probe['root_uuid']}" if probe.get("root_uuid") else probe["root_source"]
    root_fs = probe.get("root_fs") or "ext4"
    is_uefi = probe.get("boot_mode") == "uefi"
    esp_mount = probe.get("esp_mount") or "/boot/efi"
    esp_device = f"/dev/disk/by-uuid/{probe['esp_uuid']}" if probe.get("esp_uuid") else probe.get("esp_source", "")
    esp_fs = probe.get("esp_fs") or "vfat"

    configuration = f"""{{ config, pkgs, lib, modulesPath, ... }}:
{{
  imports = [ ./hardware-configuration.nix ];

  system.stateVersion = {nix_string(state_version)};

  boot.loader.timeout = 1;
  boot.tmp.cleanOnBoot = true;
  boot.kernelParams = {nix_list(kernel_params)};
  boot.initrd.availableKernelModules = {nix_list(initrd_modules)};
  boot.initrd.kernelModules = {nix_list(eval_host_json(host, "boot.initrd.kernelModules", []))};
  {("boot.loader.grub.devices = " + nix_list(grub_devices) + ";") if not is_uefi else 'boot.loader.grub.devices = [ "nodev" ];'}
  {('boot.loader.efi.efiSysMountPoint = ' + nix_string(esp_mount) + ';\n  boot.loader.grub.efiSupport = true;\n  boot.loader.grub.efiInstallAsRemovable = true;') if is_uefi else ''}

  {build_networking_nix(probe, host)}
  networking.firewall.allowedTCPPorts = [ 22 {target_port} ];

  services.openssh = {{
    enable = true;
    ports = [ 22 {target_port} ];
    settings = {{
      PermitRootLogin = "prohibit-password";
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
    }};
  }};

  users.mutableUsers = false;
  users.users.root.openssh.authorizedKeys.keys = {nix_list(ssh_keys)};
  users.users.admin = {{
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    openssh.authorizedKeys.keys = config.users.users.root.openssh.authorizedKeys.keys;
    shell = pkgs.zsh;
  }};
  security.sudo.wheelNeedsPassword = false;
  programs.zsh.enable = true;

  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  environment.systemPackages = with pkgs; [ curl git htop jq vim wget ];
  documentation.enable = false;
  documentation.doc.enable = false;
  documentation.info.enable = false;
  documentation.man.enable = false;
  documentation.nixos.enable = false;
  zramSwap.enable = true;
  systemd.coredump.enable = false;
  services.journald.extraConfig = ''
    Storage=volatile
    RuntimeMaxUse=32M
  '';
}}
"""

    hardware = f"""{{ modulesPath, ... }}:
{{
  imports = [ (modulesPath + "/profiles/qemu-guest.nix") ];
  fileSystems."/" = {{
    device = {nix_string(root_device)};
    fsType = {nix_string(root_fs)};
  }};
  {('fileSystems.' + nix_string(esp_mount) + ' = {\n    device = ' + nix_string(esp_device) + ';\n    fsType = ' + nix_string(esp_fs) + ';\n  };') if is_uefi and esp_device else ''}
}}
"""
    return configuration, hardware


def parse_probe_output(output):
    probe = {}
    list_keys = {"ipv4", "ipv6", "nameservers", "modules"}
    for raw in output.splitlines():
        if "\t" not in raw:
            continue
        key, value = raw.split("\t", 1)
        value = value.strip()
        if key in list_keys:
            probe[key] = [part for part in value.split("|") if part]
        else:
            probe[key] = value
    if not probe.get("root_source"):
        die("probe failed: missing root_source")
    if not probe.get("disk"):
        die("probe failed: missing parent disk")
    return probe


def infect_stage_slice(args):
    if args.stage not in INFECT_STAGES:
        die(f"unknown infect stage: {args.stage}")
    if args.stop_after and args.stop_after not in INFECT_STAGES:
        die(f"unknown infect stop stage: {args.stop_after}")
    start = INFECT_STAGES.index(args.stage)
    end = INFECT_STAGES.index(args.stop_after) if args.stop_after else len(INFECT_STAGES) - 1
    if end < start:
        die("--stop-after must be the same as or after --stage")
    stages = INFECT_STAGES[start : end + 1]
    if args.no_reboot:
        stages = [stage for stage in stages if stage not in {"reboot", "wait-ssh", "deploy-remote", "post-clean", "health-check"}]
    if args.no_deploy:
        stages = [stage for stage in stages if stage not in {"deploy-remote"}]
    return stages


def resolve_infect_target(host, args):
    deployment = host_deployment(host)
    target_host = deployment.get("targetHost")
    target_user = deployment.get("targetUser", "root")
    current_port = args.current_port or 22
    target_port = args.target_port or int(deployment.get("targetPort", 2234))
    if args.ssh_target:
        target_user, target_host, parsed_port, _ = normalize_ssh_target(
            args.ssh_target, default_port=22, default_user=target_user
        )
        current_port = parsed_port
    if not target_host:
        die(f"missing targetHost for {host}; pass ssh-target explicitly")
    return target_user, target_host, current_port, target_port


def confirm_infect(host, user, target_host, current_port, args):
    if args.yes or args.dry_run:
        return
    if not sys.stdin.isatty():
        die("infect is destructive; rerun with --yes in non-interactive environments")
    print(f"This will replace the OS on {user}@{target_host}:{current_port}.")
    answer = input(f"Type the host name to continue ({host}): ")
    if answer != host:
        die("confirmation did not match; aborting")


def builder_public_key(builder):
    argv = [*ssh_args(builder), "cat /root/.ssh/id_ed25519.pub 2>/dev/null || true"]
    for attempt in range(4):
        try:
            return capture(argv).strip()
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 255 or attempt >= 3:
                die(f"failed to read builder root public key via SSH; check builder-ping for {builder['name']}: {exc}")
            delay = min(2 ** attempt, 10)
            print(f"[fleet] builder SSH failed; retry {attempt + 1}/3 in {delay}s", file=sys.stderr)
            time.sleep(delay)


def check_builder_key_authorized(host, builder):
    key = builder_public_key(builder)
    if not key:
        die("builder root key missing; create /root/.ssh/id_ed25519 on the builder and add its public key to sshAuthorizedKeys")
    host_keys = eval_host_json(host, "users.users.root.openssh.authorizedKeys.keys", [])
    identities = {key_identity(item) for item in host_keys}
    if key_identity(key) not in identities:
        die("builder root public key is not authorized by the host config; add it to sshAuthorizedKeys before infect")
    return key


def target_free_mib(user, host, port, args):
    output = target_run(
        user,
        host,
        port,
        "df -Pm / | awk 'NR==2 {print $4}'",
        timeout=args.timeout,
        capture_output=True,
    )
    try:
        return int(output.strip())
    except ValueError:
        die(f"failed to parse target free space: {output!r}")


def pre_clean_target(user, host, port, args):
    script = rf"""
rm -rf {REMOTE_INFECT_DIR}
mkdir -p {REMOTE_INFECT_DIR}
if command -v apt-get >/dev/null 2>&1; then
  apt-get clean || true
fi
rm -rf \
  /tmp/* /var/tmp/* \
  /var/cache/apt/archives/* /var/lib/apt/lists/* \
  /var/log/journal /run/log/journal \
  /usr/share/doc /usr/share/man /usr/share/info \
  /usr/share/locale /usr/share/i18n /usr/share/bash-completion \
  /root/.cache
find /var/log -type f -name '*.gz' -delete 2>/dev/null || true
find /var/log -type f -exec sh -c ': > "$1"' sh {{}} \; 2>/dev/null || true
journalctl --vacuum-size=16M >/dev/null 2>&1 || true
df -hT /
timeout 30 du -xhd1 / 2>/dev/null | sort -h || true
"""
    target_run(user, host, port, script, timeout=args.timeout)
    free_mib = target_free_mib(user, host, port, args)
    if free_mib < MIN_INFECT_FREE_MIB:
        die(f"target has only {free_mib} MiB free after pre-clean; need at least {MIN_INFECT_FREE_MIB} MiB for infect")
    target_mark_stage(user, host, port, "pre-clean", timeout=args.timeout)


def post_clean_target(user, host, port, args):
    script = rf"""
rm -rf /old-root {REMOTE_INFECT_DIR} /tmp/* /var/tmp/* /root/.cache
journalctl --vacuum-size=16M >/dev/null 2>&1 || true
nix-collect-garbage -d >/dev/null 2>&1 || true
df -hT /
timeout 30 du -xhd1 / 2>/dev/null | sort -h || true
"""
    target_run(user, host, port, script, timeout=args.timeout)


def run_infect_probe(user, host, port, args):
    script = rf"""
mkdir -p {REMOTE_INFECT_DIR}
root_source=$(findmnt -n -o SOURCE / | head -n1)
root_real=$(realpath "$root_source" 2>/dev/null || printf '%s' "$root_source")
root_fs=$(findmnt -n -o FSTYPE / | head -n1)
root_uuid=$(blkid -s UUID -o value "$root_real" 2>/dev/null || true)
disk_name=$(lsblk -n -o PKNAME "$root_real" 2>/dev/null | head -n1 | tr -d '[:space:]')
partn=$(lsblk -n -o PARTN "$root_real" 2>/dev/null | head -n1 | tr -d '[:space:]')
if [ -n "$disk_name" ]; then disk="/dev/$disk_name"; else disk="$root_real"; fi
if [ -d /sys/firmware/efi ]; then boot_mode=uefi; else boot_mode=bios; fi
esp_mount=""
esp_source=""
esp_fs=""
esp_uuid=""
if [ "$boot_mode" = uefi ]; then
  for candidate in /boot/efi /boot/EFI /boot; do
    if mountpoint -q "$candidate"; then
      esp_mount="$candidate"
      esp_source=$(findmnt -n -o SOURCE "$candidate" | head -n1)
      esp_real=$(realpath "$esp_source" 2>/dev/null || printf '%s' "$esp_source")
      esp_fs=$(findmnt -n -o FSTYPE "$candidate" | head -n1)
      esp_uuid=$(blkid -s UUID -o value "$esp_real" 2>/dev/null || true)
      break
    fi
  done
fi
iface=$(ip -4 route show default 2>/dev/null | awk '{{print $5; exit}}')
if [ -z "$iface" ]; then iface=$(ip route show default 2>/dev/null | awk '{{print $5; exit}}'); fi
ipv4=$(ip -o -4 addr show scope global dev "$iface" 2>/dev/null | awk '{{print $4}}' | paste -sd '|' -)
ipv6=$(ip -o -6 addr show scope global dev "$iface" 2>/dev/null | awk '{{print $4}}' | grep -v '^fe80:' | paste -sd '|' - || true)
gateway4=$(ip -4 route show default 2>/dev/null | awk '{{print $3; exit}}')
gateway6=$(ip -6 route show default 2>/dev/null | awk '{{print $3; exit}}')
nameservers=$(awk '/^nameserver / {{print $2}}' /etc/resolv.conf | sed 's/^127\..*/1.1.1.1/; s/^::1$/2606:4700:4700::1111/' | paste -sd '|' -)
modules=$(lsmod 2>/dev/null | awk 'NR>1 {{print $1}}' | sort | paste -sd '|' -)
mem_kb=$(awk '/MemTotal/ {{print $2}}' /proc/meminfo)
kernel=$(uname -a)
for key in root_source root_real root_fs root_uuid disk partn boot_mode esp_mount esp_source esp_fs esp_uuid iface ipv4 ipv6 gateway4 gateway6 nameservers modules mem_kb kernel; do
  eval "value=\${{$key:-}}"
  printf '%s\t%s\n' "$key" "$value"
done
"""
    output = target_run(user, host, port, script, timeout=args.timeout, capture_output=True)
    probe = parse_probe_output(output)
    target_upload_text(user, host, port, f"{REMOTE_INFECT_DIR}/probe.json", json.dumps(probe, indent=2) + "\n", timeout=args.timeout)
    target_mark_stage(user, host, port, "probe", timeout=args.timeout)
    return probe


def remote_probe_json(user, host, port, args):
    try:
        return json.loads(target_read_text(user, host, port, f"{REMOTE_INFECT_DIR}/probe.json", timeout=args.timeout))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        die("missing remote probe.json; run --stage probe first")


def remote_configs_exist(user, host, port, args):
    try:
        output = target_run(
            user,
            host,
            port,
            f"if test -s {REMOTE_INFECT_DIR}/configuration.nix && test -s {REMOTE_INFECT_DIR}/hardware-configuration.nix; then echo yes; else echo no; fi",
            timeout=args.timeout,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 255:
            die("failed to verify rendered config because SSH failed; retry the same stage")
        raise
    return output.strip() == "yes"


def run_infect_script(user, host, port, nix_channel, args):
    script = rf"""
if [ -e /etc/NIXOS ] && [ ! -e /etc/NIXOS_LUSTRATE ]; then
  echo "target already appears to be NixOS; resume with --stage wait-ssh or --stage deploy-remote"
  exit 2
fi
swapoff /tmp/nixos-infect.*.swp 2>/dev/null || true
rm -f /tmp/nixos-infect.*.swp
rm -rf /nix /root/.nix-profile /root/.nix-defexpr /root/.local/state/nix 2>/dev/null || true
mkdir -p {REMOTE_INFECT_DIR}
cd {REMOTE_INFECT_DIR}
if [ ! -s nixos-infect ]; then
  if command -v curl >/dev/null 2>&1; then
    curl -L https://raw.githubusercontent.com/elitak/nixos-infect/master/nixos-infect -o nixos-infect
  else
    wget -O nixos-infect https://raw.githubusercontent.com/elitak/nixos-infect/master/nixos-infect
  fi
fi
chmod +x nixos-infect
perl -0pi -e 's#if \[\[ -n "\$SWAPSHOW" \]\]; then#if [[ -n "$SWAPSHOW" ]]; then\n    NO_SWAP=true#g' nixos-infect
perl -0pi -e 's#mktemp /tmp/nixos-infect\.XXXXX\.swp#mktemp {REMOTE_INFECT_DIR}/nixos-infect.XXXXX.swp#g; s#rm -vf /tmp/nixos-infect\.\*\.swp#rm -vf {REMOTE_INFECT_DIR}/nixos-infect.*.swp#g' nixos-infect
set -euo pipefail
NIX_CHANNEL={shlex.quote(nix_channel)} NO_REBOOT=1 bash -x ./nixos-infect 2>&1 | tee {REMOTE_INFECT_DIR}/infect.log
"""
    target_run(user, host, port, script, timeout=args.timeout, retries=0)
    target_mark_stage(user, host, port, "run-infect", timeout=args.timeout)


def builder_upload_text(builder, path, text):
    argv = [*ssh_args(builder), f"install -d -m 0755 {shlex.quote(str(Path(path).parent))}; cat > {shlex.quote(path)}"]
    printable = " ".join(shlex.quote(str(a)) for a in argv)
    print(f"+ {printable}", file=sys.stderr)
    subprocess.run(argv, input=text, text=True, check=True)


def clear_builder_known_host(builder, host, port):
    script = remote_clear_known_host_script(host, port)
    capture([*ssh_args(builder), "set -eu; " + script])


def install_target_nix(user, host, port, args):
    script = r"""
set -o pipefail
if [ ! -x /root/.nix-profile/bin/nix-store ]; then
  groupadd nixbld -g 30000 2>/dev/null || true
  for i in $(seq 1 10); do
    useradd -c "Nix build user $i" -d /var/empty -g nixbld -G nixbld -M -N -r -s "$(command -v nologin)" "nixbld$i" 2>/dev/null || true
  done
  installer_url="${NIX_INSTALL_URL:-https://nixos.org/nix/install}"
  if command -v curl >/dev/null 2>&1; then
    curl -L "$installer_url" | sh -s -- --no-channel-add
  else
    wget -O- "$installer_url" | sh -s -- --no-channel-add
  fi
fi
test -x /root/.nix-profile/bin/nix-store
install -d -m 0755 /usr/local/bin
ln -sf /root/.nix-profile/bin/nix /usr/local/bin/nix
ln -sf /root/.nix-profile/bin/nix-store /usr/local/bin/nix-store
"""
    target_run(user, host, port, script, timeout=args.timeout)


def authorize_builder_on_target(builder, user, host, port, args):
    key = builder_public_key(builder)
    script = rf"""
install -d -m 0700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
grep -qxF {shlex.quote(key)} /root/.ssh/authorized_keys || printf '%s\n' {shlex.quote(key)} >> /root/.ssh/authorized_keys
"""
    target_run(user, host, port, script, timeout=args.timeout)


def builder_build_and_copy_system(builder, target_user, target_host, target_port, configuration, hardware, nix_channel):
    work_dir = f"{builder['remote_root']}/fleet-infect-build"
    builder_upload_text(builder, f"{work_dir}/configuration.nix", configuration)
    builder_upload_text(builder, f"{work_dir}/hardware-configuration.nix", hardware)
    remote_nix = remote_nix_expr(builder)
    target = f"{target_user}@{target_host}"
    script = rf"""
work_dir={shlex.quote(work_dir)}
cd "$work_dir"
remote_nix={remote_nix}
nix_bin_dir=$(dirname "$remote_nix")
nix_build="$nix_bin_dir/nix-build"
nix_store="$nix_bin_dir/nix-store"
[ -x "$nix_build" ] || nix_build=$(command -v nix-build)
[ -x "$nix_store" ] || nix_store=$(command -v nix-store)
system=$(NIX_PATH=nixpkgs=channel:{shlex.quote(nix_channel)} "$nix_build" '<nixpkgs/nixos>' -A system -I nixos-config="$work_dir/configuration.nix" --no-out-link)
{remote_clear_known_host_script(target_host, target_port)}
"$nix_store" --export $("$nix_store" -qR "$system") | ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=60 -p {int(target_port)} {shlex.quote(target)} 'nix-store --import >/dev/null'
printf '%s\n' "$system"
"""
    output = subprocess.check_output([*ssh_args(builder), "set -eu; " + script], text=True)
    system_path = output.strip().splitlines()[-1]
    if not system_path.startswith("/nix/store/"):
        die(f"failed to parse built system path: {output!r}")
    return system_path


def activate_prebuilt_infect_system(user, host, port, system_path, probe, args):
    esp_mount = probe.get("esp_mount") or "/boot/efi"
    script = rf"""
source /root/.nix-profile/etc/profile.d/nix.sh
nix-env -p /nix/var/nix/profiles/system --set {shlex.quote(system_path)}
rm -fv /nix/var/nix/profiles/default*
/nix/var/nix/profiles/system/sw/bin/nix-collect-garbage || true
if [ -L /etc/resolv.conf ]; then mv -v /etc/resolv.conf /etc/resolv.conf.lnk; cat /etc/resolv.conf.lnk > /etc/resolv.conf; fi
touch /etc/NIXOS
: > /etc/NIXOS_LUSTRATE
printf '%s\n' etc/nixos etc/resolv.conf root/.nix-defexpr/channels >> /etc/NIXOS_LUSTRATE
(cd / && ls etc/ssh/ssh_host_*_key* 2>/dev/null || true) >> /etc/NIXOS_LUSTRATE
if [ -d /sys/firmware/efi ] && mountpoint -q {shlex.quote(esp_mount)}; then
  rm -rf {shlex.quote(esp_mount)}.bak
  cp -a {shlex.quote(esp_mount)} {shlex.quote(esp_mount)}.bak || true
  find {shlex.quote(esp_mount)} -mindepth 1 -maxdepth 1 -exec rm -rf {{}} +
fi
/nix/var/nix/profiles/system/bin/switch-to-configuration boot
"""
    target_run(user, host, port, script, timeout=args.timeout, retries=0)
    target_mark_stage(user, host, port, "run-infect", timeout=args.timeout)


def target_current_system(user, host, port, args):
    try:
        return target_run(
            user,
            host,
            port,
            "readlink /run/current-system 2>/dev/null || true",
            timeout=args.timeout,
            capture_output=True,
        ).strip()
    except subprocess.CalledProcessError:
        return ""


def target_looks_deployed(user, host, port, previous_system, args):
    if not previous_system:
        return False
    current = target_current_system(user, host, port, args)
    if not current or current == previous_system:
        return False
    script = (
        "test -e /etc/NIXOS; "
        "failed=$(systemctl --failed --no-legend --plain | wc -l); "
        'test "$failed" -eq 0'
    )
    try:
        target_run(user, host, port, script, timeout=args.timeout)
    except subprocess.CalledProcessError:
        return False
    print(f"[fleet] deploy appears applied on target: {current}", file=sys.stderr)
    return True


def install_node_age_key(user, host, port, config, args):
    key_path = repo_path(config.get("paths", {}).get("node_age_key", "local/node-age.txt"))
    if not key_path.exists():
        die(f"missing node age key: {key_path}")
    encoded = base64.b64encode(key_path.read_bytes()).decode()
    script = rf"""
install -d -m 0700 /etc/sops/age
install -d -m 0755 /etc/fleet
base64 -d > /etc/sops/age/key.txt
chmod 0400 /etc/sops/age/key.txt
touch /etc/fleet/install-method-infect
touch /etc/NIXOS_LUSTRATE
grep -qxF etc/sops/age/key.txt /etc/NIXOS_LUSTRATE || printf '%s\n' etc/sops/age/key.txt >> /etc/NIXOS_LUSTRATE
grep -qxF etc/fleet/install-method-infect /etc/NIXOS_LUSTRATE || printf '%s\n' etc/fleet/install-method-infect >> /etc/NIXOS_LUSTRATE
"""
    target_run(user, host, port, script, timeout=args.timeout, input_text=encoded)
    target_mark_stage(user, host, port, "install-secrets", timeout=args.timeout)


def infect_health_check(user, host, port, args):
    script = (
        "test -e /etc/NIXOS && echo 'NixOS: yes' || echo 'NixOS: no'; "
        "hostname; "
        "readlink /run/current-system; "
        "findmnt -no SOURCE,FSTYPE /; "
        "df -hT /; "
        "test ! -e /old-root || { echo 'leftover /old-root:'; du -shx /old-root; exit 1; }; "
        f"test ! -e {REMOTE_INFECT_DIR} || {{ echo 'leftover {REMOTE_INFECT_DIR}:'; du -shx {REMOTE_INFECT_DIR}; exit 1; }}; "
        "timeout 30 du -xhd1 / 2>/dev/null | sort -h || true; "
        "systemctl --failed --no-pager; "
        "systemctl is-active sshd || systemctl is-active ssh; "
        "systemctl is-active fail2ban || true"
    )
    target_run(user, host, port, script, timeout=args.timeout)


# ---------------------------------------------------------------------------
# StageRunner-based pipeline
# ---------------------------------------------------------------------------


def _build_infect_stages(ctx: RunContext) -> list[Stage]:
    """Build the list of Stage objects for the infect pipeline."""
    user = ctx.data["user"]
    target_host = ctx.data["target_host"]
    current_port = ctx.data["current_port"]
    target_port = ctx.data["target_port"]
    nix_channel = ctx.data["nix_channel"]
    args = ctx.args
    config = ctx.config
    builder = ctx.data["builder"]

    # Mutable port tracker shared across stages.
    ctx.data["active_port"] = current_port

    def get_port():
        return ctx.data["active_port"]

    def set_port(port):
        ctx.data["active_port"] = port

    def stage_pre_clean(ctx):
        pre_clean_target(user, target_host, get_port(), args)

    def stage_probe(ctx):
        probe = run_infect_probe(user, target_host, get_port(), args)
        ctx.data["probe"] = probe
        save_target_identity(ctx, probe, user, target_host, get_port())

    def stage_render_config(ctx):
        probe = ctx.data.get("probe")
        if probe is None:
            probe = remote_probe_json(user, target_host, get_port(), args)
            ctx.data["probe"] = probe
        configuration, hardware = render_infect_configs(args.host, probe, args)
        target_upload_text(user, target_host, get_port(), f"{REMOTE_INFECT_DIR}/configuration.nix", configuration, timeout=args.timeout)
        target_upload_text(user, target_host, get_port(), f"{REMOTE_INFECT_DIR}/hardware-configuration.nix", hardware, timeout=args.timeout)
        target_mark_stage(user, target_host, get_port(), "render-config", timeout=args.timeout)

    def stage_upload_config(ctx):
        if not remote_configs_exist(user, target_host, get_port(), args):
            die("missing rendered config; run --stage render-config first")
        target_run(
            user, target_host, get_port(),
            f"install -d -m 0755 /etc/nixos; cp {REMOTE_INFECT_DIR}/configuration.nix /etc/nixos/configuration.nix; cp {REMOTE_INFECT_DIR}/hardware-configuration.nix /etc/nixos/hardware-configuration.nix",
            timeout=args.timeout,
        )
        target_mark_stage(user, target_host, get_port(), "upload-config", timeout=args.timeout)

    def stage_run_infect(ctx):
        if getattr(args, "infect_backend", "builder") == "nixos-infect":
            run_infect_script(user, target_host, get_port(), nix_channel, args)
            return
        probe = ctx.data.get("probe")
        if probe is None:
            probe = remote_probe_json(user, target_host, get_port(), args)
            ctx.data["probe"] = probe
        configuration = target_read_text(user, target_host, get_port(), f"{REMOTE_INFECT_DIR}/configuration.nix", timeout=args.timeout)
        hardware = target_read_text(user, target_host, get_port(), f"{REMOTE_INFECT_DIR}/hardware-configuration.nix", timeout=args.timeout)
        install_target_nix(user, target_host, get_port(), args)
        authorize_builder_on_target(builder, user, target_host, get_port(), args)
        system_path = builder_build_and_copy_system(builder, user, target_host, get_port(), configuration, hardware, nix_channel)
        activate_prebuilt_infect_system(user, target_host, get_port(), system_path, probe, args)

    def stage_install_secrets(ctx):
        install_node_age_key(user, target_host, get_port(), config, args)

    def stage_reboot(ctx):
        try:
            target_run(user, target_host, get_port(), "reboot", timeout=8)
        except subprocess.CalledProcessError:
            pass
        # SSH will drop; wait for it to go down, then switch port.
        wait_ssh_down(user, target_host, get_port(), timeout=60, poll_interval=3)
        set_port(target_port)

    def stage_wait_ssh(ctx):
        set_port(target_port)
        clear_local_known_host(target_host, get_port(), force=True)
        clear_builder_known_host(builder, target_host, get_port())
        wait_ssh_up(user, target_host, get_port(), timeout=int(args.timeout), poll_interval=5)

    def stage_deploy_remote(ctx):
        set_port(target_port)
        previous_system = target_current_system(user, target_host, get_port(), args)
        clear_builder_known_host(builder, target_host, get_port())
        resume_argv = ["deploy", args.host, "--builder", builder["name"]]
        for flag, key in (
            ("--port", "port"),
            ("--ssh-key", "ssh_key"),
            ("--ssh-config", "ssh_config"),
            ("--remote-root", "remote_root"),
            ("--remote-nix", "remote_nix"),
            ("--memory", "memory"),
        ):
            value = builder.get(key)
            if value not in (None, ""):
                resume_argv.extend([flag, str(value)])
        deploy_args = argparse.Namespace(
            target=args.host,
            builder=builder["name"],
            port=builder.get("port"),
            ssh_key=builder.get("ssh_key"),
            ssh_config=builder.get("ssh_config"),
            remote_root=builder.get("remote_root"),
            remote_nix=builder.get("remote_nix"),
            memory=builder.get("memory"),
            kvm=False,
            no_kvm=not builder.get("use_kvm", False),
            non_interactive=True,
            interactive=False,
            retry=max(3, getattr(args, "retry", 0)),
            restart=False,
            resume=False,
            from_stage=None,
            stop_after=None,
            resume_argv=resume_argv,
        )
        try:
            cmd_deploy(deploy_args, config)
        except SystemExit as exc:
            if target_looks_deployed(user, target_host, get_port(), previous_system, args):
                return
            raise RuntimeError(f"deploy failed with exit code {exc.code}") from exc
        except subprocess.CalledProcessError as exc:
            if exc.returncode == 255 and target_looks_deployed(user, target_host, get_port(), previous_system, args):
                return
            raise

    def stage_post_clean(ctx):
        set_port(target_port)
        post_clean_target(user, target_host, get_port(), args)

    def stage_health_check(ctx):
        set_port(target_port)
        infect_health_check(user, target_host, get_port(), args)

    return [
        Stage(name="pre-clean", description="clean old OS caches and verify free space", run=stage_pre_clean, retryable=True),
        Stage(name="probe", description="probe target hardware/network", run=stage_probe, retryable=True),
        Stage(name="render-config", description="render NixOS configuration.nix + hardware-configuration.nix", run=stage_render_config, retryable=True),
        Stage(name="upload-config", description="upload configs to /etc/nixos", run=stage_upload_config, retryable=True),
        Stage(name="run-infect", description="run nixos-infect script", run=stage_run_infect, retryable=False, destructive=True),
        Stage(name="install-secrets", description="install node age key", run=stage_install_secrets, retryable=True),
        Stage(name="reboot", description="reboot target into NixOS", run=stage_reboot, retryable=False, destructive=True),
        Stage(name="wait-ssh", description="wait for SSH to come back on target port", run=stage_wait_ssh, retryable=True),
        Stage(name="deploy-remote", description="deploy host config from remote builder", run=stage_deploy_remote, retryable=False, destructive=True),
        Stage(name="post-clean", description="remove lustrate leftovers and collect Nix garbage", run=stage_post_clean, retryable=True),
        Stage(name="health-check", description="verify NixOS boot and services", run=stage_health_check, retryable=True, skippable=True),
    ]


def cmd_infect(args, config):
    builder = apply_builder_overrides(builder_config(config, args.builder), args)
    user, target_host, current_port, target_port = resolve_infect_target(args.host, args)
    stages = infect_stage_slice(args)
    nix_channel = infect_channel(args.host, args)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "host": args.host,
                    "target": f"{user}@{target_host}",
                    "current_port": current_port,
                    "target_port": target_port,
                    "builder": builder["name"],
                    "infect_backend": args.infect_backend,
                    "nix_channel": nix_channel,
                    "stages": stages,
                    "remote_state_dir": REMOTE_INFECT_DIR,
                },
                indent=2,
            )
        )
        return

    confirm_infect(args.host, user, target_host, current_port, args)
    if "deploy-remote" in stages:
        check_builder_key_authorized(args.host, builder)

    ctx = make_context("infect", args.host, args, config)
    ctx.data["builder"] = builder
    ctx.data["user"] = user
    ctx.data["target_host"] = target_host
    ctx.data["current_port"] = current_port
    ctx.data["target_port"] = target_port
    ctx.data["nix_channel"] = nix_channel

    resume = getattr(args, "resume", False) or args.stage != "pre-clean"
    if resume and not getattr(args, "restart", False):
        identity_port = target_port if INFECT_STAGES.index(args.stage) >= INFECT_STAGES.index("wait-ssh") else current_port
        compare_port = INFECT_STAGES.index(args.stage) < INFECT_STAGES.index("wait-ssh")
        check_resume_identity(ctx, user, target_host, identity_port, args, compare_port=compare_port)

    # Build the full stage list, then filter to the requested slice.
    all_stages = _build_infect_stages(ctx)
    stage_map = {s.name: s for s in all_stages}
    selected = [stage_map[name] for name in stages if name in stage_map]

    # infect_stage_slice already handles --stage / --stop-after / --no-reboot /
    # --no-deploy filtering.  Pass the pre-filtered list directly; the runner
    # only needs --restart for clearing markers.
    runner = StageRunner(ctx)
    runner.run_pipeline(
        selected,
        restart=getattr(args, "restart", False),
        resume=resume,
    )


def _demo():
    saved = {"user": "root", "host": "host", "port": 22, "root_uuid": "a", "disk": "/dev/vda", "boot_mode": "bios"}
    assert identity_mismatch_keys(saved, dict(saved)) == []
    changed = dict(saved)
    changed["root_uuid"] = "b"
    assert identity_mismatch_keys(saved, changed) == ["root_uuid"]
    changed = dict(saved)
    changed["port"] = 2234
    assert identity_mismatch_keys(saved, changed, compare_port=False) == []


if __name__ == "__main__":
    _demo()
