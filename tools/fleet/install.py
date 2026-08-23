"""`fleet install` — guarded, resumable nixos-anywhere fresh install.

Stages: preflight -> prepare-target -> kexec -> disko -> install -> verify.
"""

from __future__ import annotations

import json
import shlex
import shutil
import sys
import tempfile
import time
from pathlib import Path

from common import die, repo_path, run_logged
from nix import nix_eval_json, nix_eval_raw, nixos_anywhere_cmd
from orchestrator import RunContext, Stage, StageRunner, make_context
from target import normalize_ssh_target, target_run, wait_ssh_up


def _host_system(host: str) -> str:
    try:
        return nix_eval_raw(f".#nixosConfigurations.{host}.pkgs.stdenv.hostPlatform.system")
    except Exception as exc:
        die(f"could not evaluate host system for {host}: {exc}")


def _node_age_key(config) -> Path:
    path = repo_path(config.get("paths", {}).get("node_age_key", "local/node-age.txt"))
    if not path.is_file():
        die(f"missing local node age key: {path}")
    return path


def _host_disk(host: str) -> str:
    try:
        return nix_eval_raw(f".#nixosConfigurations.{host}.config.disko.devices.disk.main.device")
    except Exception as exc:
        die(f"could not evaluate disk device for {host}: {exc}")


def _host_final_ssh_port(host: str, fallback: int) -> int:
    try:
        return int(nix_eval_raw(f".#nixosConfigurations.{host}.config.my.server.ssh.port"))
    except Exception:
        return fallback


def _eval_config(host: str, path: str, default):
    try:
        return nix_eval_json(f".#nixosConfigurations.{host}.config.{path}")
    except Exception:
        return default


def _host_config_contract(host: str, system: str) -> dict:
    """Evaluate only non-secret invariants needed for a safe install."""
    root_hash = _eval_config(host, "users.users.root.hashedPassword", None)
    root_keys = _eval_config(host, "users.users.root.openssh.authorizedKeys.keys", [])
    kernel_params = _eval_config(host, "boot.kernelParams", [])
    serial_enabled = _eval_config(
        host,
        'systemd.services."serial-getty@ttyAMA0".enable',
        False,
    )
    contract = {
        "root_password": (
            isinstance(root_hash, str)
            and bool(root_hash)
            and root_hash not in {"!", "!!", "*"}
        ),
        "root_keys": isinstance(root_keys, list) and len(root_keys) > 0,
        "serial_console": bool(serial_enabled),
        "ttyAMA0_kernel_param": any("ttyAMA0" in str(item) for item in kernel_params),
    }
    if not contract["root_keys"]:
        die(f"{host} configuration has no root authorized SSH keys")
    if system == "aarch64-linux":
        missing = [
            name
            for name in ("root_password", "serial_console", "ttyAMA0_kernel_param")
            if not contract[name]
        ]
        if missing:
            die(f"{host} ARM rescue contract failed: missing {', '.join(missing)}")
    return contract


def _check_builds(ctx: RunContext) -> None:
    """Validate both the final system and disko script before touching target."""
    log_path = ctx.log_dir / "preflight.log"
    for attr in (
        f".#nixosConfigurations.{ctx.target}.config.system.build.toplevel",
        f".#nixosConfigurations.{ctx.target}.config.system.build.diskoScript",
    ):
        run_logged(
            ["nix", "build", "--dry-run", "--no-link", attr],
            log_path,
        )


def _stage_preflight(ctx: RunContext) -> None:
    user = ctx.data["user"]
    host = ctx.data["host"]
    port = ctx.data["port"]
    system = ctx.data["system"]
    disk = _host_disk(ctx.target)
    _node_age_key(ctx.config)
    contract = _host_config_contract(ctx.target, system)
    _check_builds(ctx)

    probe = target_run(
        user,
        host,
        port,
        "printf 'os='; . /etc/os-release; printf '%s\n' \"$ID\"; "
        "printf 'arch='; uname -m; "
        "printf 'efi='; test -d /sys/firmware/efi && printf yes || printf no; printf '\\n'; "
        "printf 'disk='; test -b " + shlex.quote(disk) + " && printf yes || printf no; printf '\\n'; "
        "printf 'kexec='; command -v kexec >/dev/null && printf yes || printf no; printf '\\n'; "
        "printf 'memory_mb='; awk '/MemTotal:/ {printf \"%d\\n\", $2/1024}' /proc/meminfo",
        timeout=30,
        capture_output=True,
    )
    facts = {}
    for line in probe.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            facts[key] = value.strip()

    if system == "aarch64-linux" and facts.get("arch") != "aarch64":
        die(f"host {ctx.target} requires aarch64-linux but target reports {facts.get('arch', 'unknown')}")
    if system == "aarch64-linux" and facts.get("efi") != "yes":
        die("aarch64 image host requires UEFI (/sys/firmware/efi is missing)")
    if system == "aarch64-linux" and facts.get("disk") != "yes":
        die(f"configured install disk {disk} is not present on target")
    if facts.get("memory_mb", "0").isdigit() and int(facts["memory_mb"]) < 4096:
        die(f"target has only {facts['memory_mb']} MiB RAM; at least 4096 MiB is recommended for remote install")

    ctx.data["target_facts"] = facts
    ctx.data["disk"] = disk
    ctx.data["config_contract"] = contract
    print(
        f"[fleet] preflight: system={system} target_arch={facts.get('arch', 'unknown')} "
        f"firmware={'UEFI' if facts.get('efi') == 'yes' else 'non-UEFI'} "
        f"kexec={'installed' if facts.get('kexec') == 'yes' else 'missing'}",
        file=sys.stderr,
    )


def _stage_prepare_target(ctx: RunContext) -> None:
    if not ctx.args.prepare_target:
        print("[fleet] prepare-target skipped", file=sys.stderr)
        return

    facts = ctx.data.get("target_facts")
    if facts is None:
        _stage_preflight(ctx)
        facts = ctx.data["target_facts"]
    if facts.get("kexec") == "yes":
        print("[fleet] target already has kexec-tools", file=sys.stderr)
        return
    if facts.get("os") not in {"debian", "ubuntu"}:
        die(f"automatic target preparation supports Debian/Ubuntu only, got {facts.get('os', 'unknown')}")

    target_run(
        ctx.data["user"],
        ctx.data["host"],
        ctx.data["port"],
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get update; apt-get install -y kexec-tools; "
        "command -v kexec >/dev/null",
        timeout=900,
    )


def _install_extra_files(config) -> tempfile.TemporaryDirectory:
    temp = tempfile.TemporaryDirectory(prefix="fleet-install-")
    root = Path(temp.name)
    key_path = root / "etc/sops/age/key.txt"
    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(_node_age_key(config), key_path)
    key_path.chmod(0o400)
    root.chmod(0o700)
    return temp


def build_nixos_anywhere_command(
    host: str,
    user: str,
    target: str,
    port: int,
    system: str,
    extra_files: Path | None,
    *,
    build_on: str = "auto",
    kexec_syscall: bool | None = None,
    post_kexec_ssh_port: int = 22,
    phases: str = "kexec,disko,install,reboot",
    copy_host_keys: bool = False,
    print_build_logs: bool = False,
) -> list[str]:
    if build_on == "auto":
        build_on = "remote" if system == "aarch64-linux" else "auto"
    if kexec_syscall is None:
        kexec_syscall = system == "aarch64-linux"

    cmd = nixos_anywhere_cmd()
    cmd.extend(
        [
            "--flake",
            f".#{host}",
            "--target-host",
            f"{user}@{target}",
            "--ssh-port",
            str(port),
            "--build-on",
            build_on,
            "--post-kexec-ssh-port",
            str(post_kexec_ssh_port),
            "--phases",
            phases,
        ]
    )
    if extra_files is not None:
        cmd.extend(["--extra-files", str(extra_files)])
    if kexec_syscall:
        cmd.extend(["--kexec-extra-flags", "--kexec-syscall"])
    if copy_host_keys:
        cmd.append("--copy-host-keys")
    if print_build_logs:
        cmd.append("--print-build-logs")
    return cmd


def _failure_probe_script(disk: str) -> str:
    return (
        "printf 'hostname='; hostname 2>/dev/null || true; printf '\\n'; "
        "printf 'os='; if [ -r /etc/os-release ]; then . /etc/os-release; printf '%s' \"${PRETTY_NAME:-$ID}\"; fi; printf '\\n'; "
        "printf 'arch='; uname -m 2>/dev/null || true; printf '\\n'; "
        "printf 'cmdline='; cat /proc/cmdline 2>/dev/null || true; printf '\\n'; "
        "printf 'disk='; if [ -b " + shlex.quote(disk) + " ]; then printf yes; else printf no; fi; printf '\\n'; "
        "printf 'nixos_marker='; if [ -e /etc/NIXOS ]; then printf yes; elif [ -e /mnt/etc/NIXOS ]; then printf mnt; else printf no; fi; printf '\\n'; "
        "printf 'root_profile='; readlink -f /nix/var/nix/profiles/system 2>/dev/null || true; printf '\\n'; "
        "printf 'mnt_profile='; readlink -f /mnt/nix/var/nix/profiles/system 2>/dev/null || true; printf '\\n'; "
        "printf 'mounts='; mount 2>/dev/null | grep -E '(/mnt|/boot|/dev/sda)' || true; "
        "printf 'lsblk=\\n'; lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS,PARTUUID 2>/dev/null || true; "
        "printf 'df=\\n'; df -h /mnt /mnt/boot / 2>/dev/null || true; "
        "printf 'sshd='; systemctl is-active sshd.service 2>/dev/null || true; printf '\\n'; "
        "printf 'serial_getty='; systemctl is-active serial-getty@ttyAMA0.service 2>/dev/null || true; printf '\\n'"
    )


def _collect_failure_state(ctx: RunContext, stage_name: str) -> None:
    """Probe likely target states without mutating the target."""
    ports = [
        ctx.data["post_kexec_ssh_port"],
        ctx.data["port"],
        ctx.data["final_ssh_port"],
    ]
    output = [
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"stage={stage_name}",
    ]
    disk = ctx.data.get("disk")
    if not disk:
        try:
            disk = _host_disk(ctx.target)
        except Exception as exc:
            output.append(f"disk=unavailable ({exc})")
            disk = "/dev/null"
    for port in dict.fromkeys(ports):
        try:
            probe = target_run(
                ctx.data["user"],
                ctx.data["host"],
                port,
                _failure_probe_script(disk),
                timeout=15,
                capture_output=True,
                retries=0,
            )
        except Exception as exc:
            output.append(f"--- port {port}: unreachable ({exc}) ---")
            continue
        output.append(f"--- port {port}: reachable ---")
        output.append(probe.rstrip())
    path = ctx.log_dir / f"{stage_name}-failure-state.txt"
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"[fleet] failure state saved to {path}", file=sys.stderr)


def _probe_install_retry(ctx: RunContext) -> bool:
    """Re-probe the endpoint used by the failed phase before allowing retry."""
    stage_name = ctx.data.get("current_stage", "unknown")
    _collect_failure_state(ctx, f"{stage_name}-retry-probe")
    port = ctx.data.get("current_port")
    if port is None:
        return False
    try:
        target_run(
            ctx.data["user"],
            ctx.data["host"],
            port,
            "true",
            timeout=15,
            capture_output=True,
            retries=0,
        )
    except Exception as exc:
        print(f"[fleet] retry probe: SSH endpoint {port} is not reachable ({exc})", file=sys.stderr)
        return False
    print(f"[fleet] retry probe: SSH endpoint {port} is reachable", file=sys.stderr)
    return True


def _run_nixos_anywhere(ctx: RunContext, *, port: int, phases: str, extra_files: bool) -> None:
    temp = _install_extra_files(ctx.config) if extra_files else None
    try:
        cmd = build_nixos_anywhere_command(
            ctx.target,
            ctx.data["user"],
            ctx.data["host"],
            port,
            ctx.data["system"],
            Path(temp.name) if temp is not None else None,
            build_on=ctx.args.build_on,
            kexec_syscall=ctx.args.kexec_syscall,
            post_kexec_ssh_port=ctx.data["post_kexec_ssh_port"],
            phases=phases,
            copy_host_keys=ctx.args.copy_host_keys,
            print_build_logs=ctx.args.print_build_logs,
        )
        run_logged(cmd, ctx.log_dir / f"{ctx.data['current_stage']}.log")
    finally:
        if temp is not None:
            temp.cleanup()


def _stage_phase(ctx: RunContext, stage_name: str, *, port: int, phases: str, extra_files: bool) -> None:
    ctx.data["current_stage"] = stage_name
    ctx.data["current_port"] = port
    try:
        _run_nixos_anywhere(ctx, port=port, phases=phases, extra_files=extra_files)
    except Exception:
        _collect_failure_state(ctx, stage_name)
        raise


def _stage_kexec(ctx: RunContext) -> None:
    _stage_phase(
        ctx,
        "kexec",
        port=ctx.data["port"],
        phases="kexec",
        extra_files=False,
    )


def _stage_disko(ctx: RunContext) -> None:
    _stage_phase(
        ctx,
        "disko",
        port=ctx.data["post_kexec_ssh_port"],
        phases="disko",
        extra_files=False,
    )


def _stage_install(ctx: RunContext) -> None:
    _stage_phase(
        ctx,
        "install",
        port=ctx.data["post_kexec_ssh_port"],
        phases="install,reboot",
        extra_files=True,
    )


def _target_health_script(ctx: RunContext) -> str:
    disk = shlex.quote(_host_disk(ctx.target))
    serial = "systemctl is-active serial-getty@ttyAMA0.service 2>/dev/null || true" if ctx.data["system"] == "aarch64-linux" else "printf not-required"
    return (
        "printf 'nixos='; test -e /etc/NIXOS && printf yes || printf no; printf '\\n'; "
        "printf 'version='; nixos-version 2>/dev/null || true; printf '\\n'; "
        "printf 'system='; readlink -f /nix/var/nix/profiles/system; printf '\\n'; "
        "printf 'disk='; test -b " + disk + " && printf yes || printf no; printf '\\n'; "
        "printf 'root_mount='; findmnt -no SOURCE / 2>/dev/null || true; printf '\\n'; "
        "printf 'boot_mount='; findmnt -no SOURCE /boot 2>/dev/null || true; printf '\\n'; "
        "printf 'sshd='; systemctl is-active sshd.service 2>/dev/null || true; printf '\\n'; "
        "printf 'serial_getty='; " + serial + "; printf '\\n'; "
        "printf 'root_password='; awk -F: '$1==\"root\" {if ($2 ~ /^\\$[a-z]/ || ($2 != \"\" && $2 != \"!\" && $2 != \"!!\" && $2 != \"*\")) print \"ok\"; else print \"missing\"}' /etc/shadow; "
        "printf 'root_keys='; if test -s /etc/ssh/authorized_keys.d/root || test -s /root/.ssh/authorized_keys; then printf yes; else printf no; fi; printf '\\n'; "
        "printf 'sops_key='; test -r /etc/sops/age/key.txt && printf yes || printf no; printf '\\n'; "
        "printf 'console='; cat /proc/cmdline 2>/dev/null | grep -q ttyAMA0 && printf ttyAMA0 || printf missing; printf '\\n'; "
        "printf 'port='; ss -lnt 2>/dev/null | grep -qE ':" + str(ctx.data["final_ssh_port"]) + "\\b' && printf yes || printf no; printf '\\n'"
    )


def _stage_verify(ctx: RunContext) -> None:
    port = ctx.data["final_ssh_port"]
    wait_ssh_up(ctx.data["user"], ctx.data["host"], port, timeout=900, poll_interval=5)
    health = target_run(
        ctx.data["user"],
        ctx.data["host"],
        port,
        _target_health_script(ctx),
        timeout=30,
        capture_output=True,
    )
    facts = {}
    for line in health.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            facts[key] = value.strip()
    (ctx.log_dir / "verify.log").write_text(health, encoding="utf-8")
    required = {
        "nixos": "yes",
        "disk": "yes",
        "sshd": "active",
        "root_password": "ok",
        "root_keys": "yes",
        "sops_key": "yes",
        "console": "ttyAMA0" if ctx.data["system"] == "aarch64-linux" else facts.get("console", "missing"),
        "port": "yes",
    }
    if ctx.data["system"] == "aarch64-linux":
        required["serial_getty"] = "active"
    failures = [f"{key}={facts.get(key, 'missing')} (expected {value})" for key, value in required.items() if facts.get(key) != value]
    if failures:
        die("post-install health check failed: " + "; ".join(failures))
    print(
        f"[fleet] install verified: SSH reachable on "
        f"{ctx.data['user']}@{ctx.data['host']}:{port}",
        file=sys.stderr,
    )


def confirm_install(host, user, target_host, port, args):
    backup_ref = getattr(args, "backup_ref", None)
    if not backup_ref and not getattr(args, "allow_no_backup", False):
        die(
            "destructive install requires --backup-ref <provider-backup-reference>; "
            "use --allow-no-backup only after explicitly accepting the recovery risk"
        )
    if getattr(args, "yes", False):
        return
    if not sys.stdin.isatty():
        die("install is destructive; rerun with --yes in non-interactive environments")
    if backup_ref:
        print(f"Recovery backup reference: {backup_ref}")
    else:
        print("WARNING: no provider backup reference was supplied (--allow-no-backup).")
    print(f"This will erase the disk on {user}@{target_host}:{port} and install NixOS.")
    answer = input(f"Type the host name to continue ({host}): ")
    if answer != host:
        die("confirmation did not match; aborting")


def _write_install_manifest(ctx: RunContext) -> None:
    manifest = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": ctx.target,
        "target": f"{ctx.data['user']}@{ctx.data['host']}",
        "providerPort": ctx.data["port"],
        "postKexecPort": ctx.data["post_kexec_ssh_port"],
        "finalPort": ctx.data["final_ssh_port"],
        "system": ctx.data["system"],
        "backupRef": getattr(ctx.args, "backup_ref", None),
        "allowNoBackup": bool(getattr(ctx.args, "allow_no_backup", False)),
        "stages": ["preflight", "prepare-target", "kexec", "disko", "install", "verify"],
    }
    (ctx.state_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def cmd_install(args, config):
    user, host, port, _ = normalize_ssh_target(
        args.ssh_target, default_port=22, default_user="root"
    )
    system = _host_system(args.host)
    ctx = make_context("install", args.host, args, config)
    final_ssh_port = _host_final_ssh_port(args.host, port)
    ctx.data.update(
        user=user,
        host=host,
        port=port,
        post_kexec_ssh_port=args.post_kexec_ssh_port,
        final_ssh_port=final_ssh_port,
        system=system,
    )

    if args.dry_run:
        print("[fleet] dry-run: no target connection or disk operation will occur", file=sys.stderr)
        commands = (
            ("kexec", port, "kexec", False),
            ("disko", args.post_kexec_ssh_port, "disko", False),
            ("install", args.post_kexec_ssh_port, "install,reboot", True),
        )
        for name, stage_port, phases, extra_files in commands:
            extra = Path("/tmp/fleet-install-files") if extra_files else None
            cmd = build_nixos_anywhere_command(
                args.host,
                user,
                host,
                stage_port,
                system,
                extra,
                build_on=args.build_on,
                kexec_syscall=args.kexec_syscall,
                post_kexec_ssh_port=args.post_kexec_ssh_port,
                phases=phases,
                copy_host_keys=args.copy_host_keys,
                print_build_logs=args.print_build_logs,
            )
            print(f"[{name}] + " + " ".join(shlex.quote(str(item)) for item in cmd), file=sys.stderr)
        return

    _write_install_manifest(ctx)

    stop_after = getattr(args, "stop_after", None)
    from_stage = getattr(args, "from_stage", None)
    stage_names = ["preflight", "prepare-target", "kexec", "disko", "install", "verify"]
    start_idx = stage_names.index(from_stage) if from_stage else 0
    stop_idx = stage_names.index(stop_after) if stop_after else len(stage_names) - 1
    destructive_names = {"kexec", "disko", "install"}
    destructive_will_run = any(
        start_idx <= index <= stop_idx
        for index, name in enumerate(stage_names)
        if name in destructive_names
    )
    if getattr(args, "resume", False) and not getattr(args, "restart", False):
        destructive_will_run = any(
            start_idx <= index <= stop_idx
            and name in destructive_names
            and not (ctx.state_dir / f"{name}.done").exists()
            for index, name in enumerate(stage_names)
        )
    if destructive_will_run:
        confirm_install(args.host, user, host, port, args)

    stages = [
        Stage(name="preflight", description="check target architecture, firmware, disk, and prerequisites", run=_stage_preflight, retryable=False, continueable=False),
        Stage(name="prepare-target", description="install target kexec prerequisites", run=_stage_prepare_target, retryable=False, continueable=False),
        Stage(name="kexec", description=f"boot {args.host} into the NixOS installer", run=_stage_kexec, retryable=False, destructive=True, retry_probe=_probe_install_retry),
        Stage(name="disko", description=f"format and mount the configured disk for {args.host}", run=_stage_disko, retryable=False, destructive=True, retry_probe=_probe_install_retry),
        Stage(name="install", description=f"install {args.host} and reboot into NixOS", run=_stage_install, retryable=False, destructive=True, retry_probe=_probe_install_retry),
        Stage(name="verify", description="verify SSH reachable after install reboot", run=_stage_verify, retryable=True),
    ]
    runner = StageRunner(ctx)
    runner.run_pipeline(
        stages,
        restart=getattr(args, "restart", False),
        resume=getattr(args, "resume", False) or getattr(args, "from_stage", None) is not None,
        from_stage=getattr(args, "from_stage", None),
        stop_after=getattr(args, "stop_after", None),
    )
