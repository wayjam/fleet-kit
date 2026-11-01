"""`fleet deploy <target>` and `fleet deploy-all`.

With ``--builder``: sync the local worktree to the remote builder and apply
from there (merges the old ``deploy-remote`` recipe).

Remote-builder deploy is split into stages for resume / retry / interactivity:
  sync → lock → apply
"""

import shlex
import subprocess
import sys

from builder import (
    apply_builder_overrides,
    builder_config,
    lock_fleetkit_on_builder,
    remote_nix_expr,
    remote_shell,
    ssh_args,
    sync_to_builder,
)
from common import run
from console import status as format_status
from nix import colmena_cmd, eval_host_raw, host_deployment, nixos_host_names
from orchestrator import RunContext, Stage, StageRunner, make_context


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


def _stage_sync(ctx: RunContext) -> None:
    builder = ctx.data["builder"]
    sync_to_builder(ctx.config, builder)


def _stage_lock(ctx: RunContext) -> None:
    builder = ctx.data["builder"]
    lock_fleetkit_on_builder(ctx.config, builder)


def _stage_target_ssh_preflight(ctx: RunContext) -> None:
    """Verify the builder can reach the current target before building/applying."""
    host = ctx.data["deploy_target"]
    deployment = host_deployment(host)
    target_host = deployment.get("targetHost")
    if not target_host:
        raise RuntimeError(f"deployment.targetHost is missing for {host}")

    target_user = str(deployment.get("targetUser", "root"))
    if "@" in str(target_host):
        target_user, target_host = str(target_host).rsplit("@", 1)
    target_port = int(deployment.get("targetPort", 22))
    target = f"{target_user}@{target_host}"
    probe = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "ConnectionAttempts=1",
        "-p", str(target_port),
        target,
        "true",
    ]
    command = " ".join(shlex.quote(part) for part in probe)
    try:
        remote_shell(ctx.data["builder"], command)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"builder '{ctx.data['builder']['name']}' cannot SSH to {target}:{target_port}. "
            "Authorize the builder's public key in the target's currently active SSH keys, "
            "then resume with `--resume --from-stage target-preflight`."
        ) from exc


def _target_probe_command(target_user, target_host, target_port, script):
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "ConnectionAttempts=1",
        "-p", str(target_port),
        f"{target_user}@{target_host}",
        script,
    ]


def _dbus_probe_script():
    return (
        "set -eu; pid=$(systemctl show dbus.service -p MainPID --value 2>/dev/null || true); "
        "exe=unknown; impl=unknown; configured_exe=unknown; configured_impl=unknown; "
        "case $pid in ''|0|*[!0-9]*) ;; *) "
        "exe=$(readlink -f /proc/$pid/exe 2>/dev/null || true); "
        "case $exe in *dbus-broker-launch) impl=broker ;; *dbus-daemon) impl=dbus ;; esac ;; esac; "
        "unit_exec=$(systemctl show dbus.service -p ExecStart --value 2>/dev/null || true); "
        "configured_exe=$(printf '%s' \"$unit_exec\" | sed -n 's/.*path=\\([^ ;}]*\\).*/\\1/p'); "
        "configured_exe=$(readlink -f \"$configured_exe\" 2>/dev/null || true); "
        "case $configured_exe in *dbus-broker-launch) configured_impl=broker ;; *dbus-daemon) configured_impl=dbus ;; esac; "
        "printf 'running_dbus=%s\\n' \"$impl\"; printf 'running_dbus_exe=%s\\n' \"$exe\"; "
        "printf 'configured_dbus=%s\\n' \"$configured_impl\"; printf 'configured_dbus_exe=%s\\n' \"$configured_exe\""
    )


def _target_output(ctx, deployment, script):
    target_host = str(deployment.get("targetHost", ""))
    target_user = str(deployment.get("targetUser", "root"))
    if "@" in target_host:
        target_user, target_host = target_host.rsplit("@", 1)
    target_port = int(deployment.get("targetPort", 22))
    command = _target_probe_command(target_user, target_host, target_port, script)
    if ctx.data.get("builder"):
        result = subprocess.run(
            [*ssh_args(ctx.data["builder"]), " ".join(shlex.quote(part) for part in command)],
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"target probe exited {result.returncode}")
    return result.stdout


def _stage_dbus_preflight(ctx, deployment=None):
    host = ctx.data["deploy_target"]
    deployment = deployment or host_deployment(host)
    target_impl = eval_host_raw(host, "services.dbus.implementation", "unknown")
    if target_impl not in {"dbus", "broker"}:
        raise RuntimeError(f"cannot determine target D-Bus implementation ({target_impl}); refusing deployment")

    try:
        output = _target_output(ctx, deployment, _dbus_probe_script())
    except Exception as exc:
        raise RuntimeError(
            f"cannot determine the target's running D-Bus implementation ({exc}); "
            "refusing an online activation with unknown D-Bus state"
        ) from exc
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    running_impl = values.get("running_dbus", "unknown")
    if running_impl == "unknown" and getattr(ctx.args, "activation", "switch") != "boot":
        raise RuntimeError(
            "cannot identify the running D-Bus process; refusing online activation. "
            "Inspect the host or use `--activation boot` if a controlled reboot is planned."
        )
    if running_impl == target_impl:
        print(format_status(
            "✓ D-BUS OK",
            f"running and target implementations match ({target_impl})",
            level="success",
            stream=sys.stderr,
        ), file=sys.stderr)
        ctx.data["dbus_preflight_ok"] = True
        return

    if getattr(ctx.args, "activation", "switch") == "boot":
        print(format_status(
            "! REBOOT REQUIRED",
            f"D-Bus {running_impl} → {target_impl}; boot activation selected. "
            "After deployment, reboot the host manually and run `just verify <host>`. ",
            level="warning",
            stream=sys.stderr,
        ), file=sys.stderr)
        ctx.data["dbus_preflight_ok"] = True
        return

    raise RuntimeError(
        f"D-Bus implementation transition detected: running={running_impl}, target={target_impl}. "
        "NixOS 26.05's switch inhibitor cannot compare this key when the running generation "
        "predates inhibitors. Do not use online switch; deploy with `--activation boot`, "
        "reboot the host manually when ready, then run `just verify <host>`."
    )


def _stage_dbus_preflight_all(ctx):
    try:
        hosts = nixos_host_names()
    except Exception as exc:
        raise RuntimeError(f"cannot enumerate NixOS hosts for D-Bus preflight: {exc}") from exc
    original_target = ctx.data.get("deploy_target")
    complete = False
    try:
        for host in hosts:
            ctx.data["deploy_target"] = host
            print(f"[fleet] D-Bus preflight: checking {host}...", file=sys.stderr)
            _stage_dbus_preflight(ctx)
        complete = True
    finally:
        ctx.data["deploy_target"] = original_target
        ctx.data["dbus_preflight_ok"] = complete


def _dbus_preflight_stage(name, description, run_stage):
    return Stage(
        name=name,
        description=description,
        run=run_stage,
        retryable=False,
        continueable=False,
    )


def _post_apply_diagnostic(ctx, cause):
    host = ctx.data.get("deploy_target")
    if not host:
        original_target = ctx.data.get("deploy_target")
        reports = []
        try:
            for target in nixos_host_names():
                ctx.data["deploy_target"] = target
                reports.append(f"[{target}] {_post_apply_diagnostic(ctx, cause)}")
        except Exception as exc:
            reports.append(f"host enumeration failed: {exc}")
        finally:
            ctx.data["deploy_target"] = original_target
        return f"deploy-all apply failed ({cause}); per-host read-only probes:\n" + "\n\n".join(reports)
    try:
        deployment = host_deployment(host)
        script = (
            "set +e; "
            "printf 'generation='; readlink -f /run/current-system 2>/dev/null || echo unknown; "
            "printf 'system_profile='; readlink -f /nix/var/nix/profiles/system 2>/dev/null || echo unknown; "
            f"{_dbus_probe_script()}; "
            "printf 'system_state='; systemctl is-system-running 2>/dev/null || true; "
            "printf 'failed_units='; systemctl --failed --no-legend 2>/dev/null | awk '{print $1}' | paste -sd, -; "
            "if busctl --system list >/dev/null 2>&1; then echo bus=ok; else echo bus=fail; fi"
        )
        output = _target_output(ctx, deployment, script).strip()
    except Exception as exc:
        return (
            f"apply failed ({cause}); post-apply target state is UNKNOWN ({exc}). "
            "Do not retry or reboot until target access/state is confirmed."
        )

    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    try:
        target_impl = eval_host_raw(host, "services.dbus.implementation", "unknown")
        target_generation = eval_host_raw(host, "system.build.toplevel", "")
    except Exception as exc:
        return f"apply failed ({cause}); could not evaluate target configuration ({exc}); probe:\n{output}"
    generation = values.get("generation", "unknown")
    system_profile = values.get("system_profile", "unknown")
    running_impl = values.get("running_dbus", "unknown")
    if running_impl == "unknown":
        state = "running D-Bus implementation could not be identified; reboot is not yet a verified remedy"
    elif target_impl in {"dbus", "broker"} and running_impl != target_impl:
        if target_generation and generation == target_generation:
            state = "target generation is active but its D-Bus implementation is not; controlled reboot required"
        elif target_generation and system_profile == target_generation:
            state = "target generation is installed for boot but not active; controlled reboot and verification required"
        else:
            state = "D-BUS differs from target, but target generation is not active; reboot is not yet a verified remedy"
    else:
        failed_units = values.get("failed_units", "")
        if values.get("bus") != "ok":
            state = "system D-Bus probe failed; inspect before retrying or rebooting"
        elif failed_units:
            state = f"failed systemd units detected ({failed_units}); inspect affected services"
        elif generation != target_generation:
            state = "target generation is not active; inspect activation failure before retrying"
        else:
            state = "generation and D-Bus match, but apply returned non-zero; inspect activation logs"
    return (
        f"apply failed ({cause}); post-apply state: {state}. "
        f"Read-only target probe:\n{output}\n"
        "Do not blindly retry apply. Follow the classification above; reboot only when the "
        "target generation is confirmed active or installed for boot, then run `just verify <host>`."
    )


def _stage_apply_remote(ctx: RunContext) -> None:
    if not ctx.data.get("dbus_preflight_ok"):
        if ctx.data.get("deploy_target"):
            _stage_dbus_preflight(ctx)
        else:
            _stage_dbus_preflight_all(ctx)
    builder = ctx.data["builder"]
    repos = ctx.config.get("repos", {})
    inventory_name = repos.get("inventory_name", "fleet-inventory")
    remote_root = builder["remote_root"]
    remote_nix = remote_nix_expr(builder)
    on_flag = f" --on {shlex.quote(ctx.data['deploy_target'])}" if ctx.data.get("deploy_target") else ""
    activation = getattr(ctx.args, "activation", "switch")
    goal = "boot" if activation == "boot" else "switch"
    script = (
        f"cd {shlex.quote(remote_root + '/' + inventory_name)}; "
        f"remote_nix={remote_nix}; "
        f"$remote_nix run .#colmena -- --impure --config flake.nix apply {goal}{on_flag}"
    )
    try:
        remote_shell(builder, script)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(_post_apply_diagnostic(ctx, f"exit {exc.returncode}")) from exc


def _stage_apply_local(ctx: RunContext) -> None:
    on_args = ["--on", ctx.data["deploy_target"]] if ctx.data.get("deploy_target") else []
    goal = "boot" if getattr(ctx.args, "activation", "switch") == "boot" else "switch"
    try:
        run([*colmena_cmd(), "apply", goal, *on_args])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(_post_apply_diagnostic(ctx, f"exit {exc.returncode}")) from exc


# ---------------------------------------------------------------------------
# Public command entry points
# ---------------------------------------------------------------------------


def cmd_deploy(args, config):
    if not hasattr(args, "activation"):
        args.activation = "switch"
    if args.builder:
        builder = apply_builder_overrides(builder_config(config, args.builder), args)
        ctx = make_context("deploy", args.target, args, config)
        ctx.data["builder"] = builder
        ctx.data["deploy_target"] = args.target

        stages = [
            Stage(name="sync", description="sync worktree to builder", run=_stage_sync, retryable=True),
            Stage(name="lock", description="flake lock --override-input on builder", run=_stage_lock, retryable=True),
            Stage(
                name="target-preflight",
                description=f"verify builder SSH access to {args.target}",
                run=_stage_target_ssh_preflight,
                retryable=True,
            ),
            _dbus_preflight_stage(
                "dbus-preflight",
                f"check whether {args.target} can safely switch D-Bus online",
                _stage_dbus_preflight,
            ),
            Stage(name="apply", description=f"colmena apply --on {args.target} on builder", run=_stage_apply_remote, retryable=False, destructive=True),
        ]
        runner = StageRunner(ctx)
        runner.run_pipeline(
            stages,
            restart=getattr(args, "restart", False),
            resume=getattr(args, "resume", False) or getattr(args, "from_stage", None) is not None,
            from_stage=getattr(args, "from_stage", None),
            stop_after=getattr(args, "stop_after", None),
        )
    else:
        ctx = make_context("deploy", args.target, args, config)
        ctx.data["deploy_target"] = args.target
        _stage_dbus_preflight(ctx)
        _stage_apply_local(ctx)


def cmd_deploy_all(args, config):
    if not hasattr(args, "activation"):
        args.activation = "switch"
    if args.builder:
        builder = apply_builder_overrides(builder_config(config, args.builder), args)
        ctx = make_context("deploy-all", "all", args, config)
        ctx.data["builder"] = builder
        ctx.data["deploy_target"] = None  # apply all hosts

        stages = [
            Stage(name="sync", description="sync worktree to builder", run=_stage_sync, retryable=True),
            Stage(name="lock", description="flake lock --override-input on builder", run=_stage_lock, retryable=True),
            _dbus_preflight_stage(
                "dbus-preflight",
                "check D-Bus implementation compatibility on every host",
                _stage_dbus_preflight_all,
            ),
            Stage(name="apply", description="colmena apply (all hosts) on builder", run=_stage_apply_remote, retryable=False, destructive=True),
        ]
        runner = StageRunner(ctx)
        runner.run_pipeline(
            stages,
            restart=getattr(args, "restart", False),
            resume=getattr(args, "resume", False) or getattr(args, "from_stage", None) is not None,
            from_stage=getattr(args, "from_stage", None),
            stop_after=getattr(args, "stop_after", None),
        )
    else:
        ctx = make_context("deploy-all", "all", args, config)
        ctx.data["deploy_target"] = None
        _stage_dbus_preflight_all(ctx)
        goal = "boot" if args.activation == "boot" else "switch"
        try:
            run([*colmena_cmd(), "apply", goal])
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(_post_apply_diagnostic(ctx, f"exit {exc.returncode}")) from exc


def cmd_verify(args, _config):
    """Read-only post-deployment verification for one NixOS host."""
    host = args.host
    deployment = host_deployment(host)
    expected_generation = eval_host_raw(host, "system.build.toplevel", "")
    expected_dbus = eval_host_raw(host, "services.dbus.implementation", "unknown")
    if not expected_generation or expected_dbus not in {"dbus", "broker"}:
        print("fleet verify: cannot evaluate expected system generation or D-Bus implementation", file=sys.stderr)
        raise SystemExit(2)

    unit_probes = " ".join(shlex.quote(unit) for unit in args.unit)
    unit_script = (
        f"for unit in {unit_probes}; do "
        "state=$(systemctl is-active \"$unit\" 2>/dev/null || true); "
        "printf 'unit:%s=%s\\n' \"$unit\" \"$state\"; done; "
        if args.unit
        else ":; "
    )
    script = (
        "set +e; "
        "printf 'generation='; readlink -f /run/current-system 2>/dev/null || echo unknown; "
        "printf 'system_profile='; readlink -f /nix/var/nix/profiles/system 2>/dev/null || echo unknown; "
        f"{_dbus_probe_script()}; "
        "printf 'system_state='; systemctl is-system-running 2>/dev/null || true; "
        "printf 'failed_units='; systemctl --failed --no-legend 2>/dev/null | awk '{print $1}' | paste -sd, -; "
        "if busctl --system list >/dev/null 2>&1; then echo bus=ok; else echo bus=fail; fi; "
        f"{unit_script}"
    )

    try:
        output = _target_output(type("Context", (), {"data": {}})(), deployment, script).strip()
    except Exception as exc:
        print(f"fleet verify: target state is UNKNOWN ({exc})", file=sys.stderr)
        raise SystemExit(2) from exc

    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    failures = []
    generation = values.get("generation", "unknown")
    system_profile = values.get("system_profile", "unknown")
    if generation != system_profile:
        failures.append("running generation does not match the system profile selected for boot")
    if values.get("running_dbus") == "unknown":
        failures.append("could not identify the running D-Bus implementation")
    if values.get("configured_dbus") != values.get("running_dbus"):
        failures.append(
            "running D-Bus process does not match the active systemd unit "
            f"(running={values.get('running_dbus', 'unknown')}, configured={values.get('configured_dbus', 'unknown')})"
        )
    if values.get("bus") != "ok":
        failures.append("system D-Bus is not responding")
    failed_units = values.get("failed_units", "")
    if failed_units:
        failures.append(f"failed systemd units: {failed_units}")
    for unit in args.unit:
        if values.get(f"unit:{unit}") != "active":
            failures.append(f"required unit is not active: {unit}")

    config_drift = generation != expected_generation or values.get("running_dbus") != expected_dbus
    if getattr(args, "strict_generation", False) and generation != expected_generation:
        failures.append("running generation does not match the currently evaluated local configuration")
    status = "FAILED" if failures else ("OK (runtime healthy; local config differs)" if config_drift else "OK")
    level = "error" if failures else ("warning" if config_drift else "success")
    print(format_status(f"fleet verify: {status}", f"for {host}", level=level, stream=sys.stdout))
    print(output)
    if config_drift:
        print(
            f"fleet verify: local target is {expected_generation} with D-Bus={expected_dbus}; "
            f"host is running {generation} with D-Bus={values.get('running_dbus', 'unknown')}. "
            "This may mean the local flake changed after deployment. Use --strict-generation "
            "to require exact equality.",
            file=sys.stderr,
        )
    if failures:
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)
