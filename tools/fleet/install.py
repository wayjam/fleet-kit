"""`fleet install` — nixos-anywhere fresh install.

Stage-based with destructive confirmation and post-install SSH verification:
  install → verify
"""

import sys

from common import die, run
from nix import nixos_anywhere_cmd
from orchestrator import RunContext, Stage, StageRunner, make_context
from target import normalize_ssh_target, wait_ssh_up


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


def _stage_install(ctx: RunContext) -> None:
    """Run nixos-anywhere to install NixOS on the target."""
    user = ctx.data["user"]
    host = ctx.data["host"]
    port = ctx.data["port"]
    args = ctx.args

    cmd = nixos_anywhere_cmd()
    if port and port != 22:
        cmd.extend(["--ssh-option", f"Port={port}"])
    if getattr(args, "kexec_syscall", False):
        cmd.extend(["--kexec-extra-flags", "--kexec-syscall"])
    cmd.extend(["--flake", f".#{args.host}", f"{user}@{host}"])
    run(cmd)


def _stage_verify(ctx: RunContext) -> None:
    """Verify the target is reachable after install."""
    user = ctx.data["user"]
    host = ctx.data["host"]
    port = ctx.data["port"]
    # nixos-anywhere reboots the target; wait for it to come back.
    wait_ssh_up(user, host, port, timeout=600, poll_interval=5)
    print(f"[fleet] install verified: SSH reachable on {user}@{host}:{port}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Destructive confirmation
# ---------------------------------------------------------------------------


def confirm_install(host, user, target_host, port, args):
    """Require explicit confirmation for the destructive install."""
    if getattr(args, "yes", False):
        return
    if not sys.stdin.isatty():
        die("install is destructive; rerun with --yes in non-interactive environments")
    print(f"This will erase the disk on {user}@{target_host}:{port} and install NixOS.")
    answer = input(f"Type the host name to continue ({host}): ")
    if answer != host:
        die("confirmation did not match; aborting")


# ---------------------------------------------------------------------------
# Public command entry point
# ---------------------------------------------------------------------------


def cmd_install(args, config):
    user, host, port, _ = normalize_ssh_target(
        args.ssh_target, default_port=22, default_user="root"
    )

    confirm_install(args.host, user, host, port, args)

    ctx = make_context("install", args.host, args, config)
    ctx.data["user"] = user
    ctx.data["host"] = host
    ctx.data["port"] = port

    stages = [
        Stage(
            name="install",
            description=f"nixos-anywhere install of {args.host} on {user}@{host}:{port}",
            run=_stage_install,
            retryable=False,
            destructive=True,
        ),
        Stage(
            name="verify",
            description="verify SSH reachable after install reboot",
            run=_stage_verify,
            retryable=True,
        ),
    ]
    runner = StageRunner(ctx)
    runner.run_pipeline(
        stages,
        restart=getattr(args, "restart", False),
        resume=getattr(args, "resume", False) or getattr(args, "from_stage", None) is not None,
        from_stage=getattr(args, "from_stage", None),
        stop_after=getattr(args, "stop_after", None),
    )
