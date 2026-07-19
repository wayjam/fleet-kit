"""`fleet image <host>` and `fleet download-image <host>`.

Unified commands that replace the old ``image build``, ``image remote``,
and ``image download`` subcommands.

Remote non-KVM builds use :mod:`remote_job` for structured status monitoring
and artifact verification, replacing the old pid-only heartbeat.
"""

import shlex
from pathlib import Path

from builder import (
    apply_builder_overrides,
    builder_config,
    builder_spec,
    detect_fleetkit_mode,
    fleetkit_input_name,
    nix_ssh_env,
    remote_nix_expr,
    remote_repo_path,
    scp_args,
    sync_to_builder,
)
from common import repo_path, run
from orchestrator import RunContext, Stage, StageRunner, make_context
from remote_job import job_remote_dir, make_job_id, start_remote_job, verify_remote_artifact, wait_remote_job


# ---------------------------------------------------------------------------
# Stage implementations — remote non-KVM image build
# ---------------------------------------------------------------------------


def _stage_sync(ctx: RunContext) -> None:
    builder = ctx.data["builder"]
    sync_to_builder(ctx.config, builder)


def _stage_remote_build(ctx: RunContext) -> None:
    """Start and wait for the disko image build on the builder."""
    builder = ctx.data["builder"]
    host = ctx.target
    config = ctx.config
    repos = config.get("repos", {})
    public_name = repos.get("public_name", "fleet-kit")
    inventory_name = repos.get("inventory_name", "fleet-inventory")
    remote_root = builder["remote_root"]
    remote_nix = remote_nix_expr(builder)
    paths = config.get("paths", {})
    node_age_key = paths.get("node_age_key", "local/node-age.txt")
    node_age_key_arg = ""
    if node_age_key and repo_path(node_age_key).exists():
        node_age_key_arg = (
            " --post-format-files "
            + shlex.quote(remote_repo_path(config, node_age_key, builder))
            + " /etc/sops/age/key.txt"
        )

    out_dir = ctx.data["out_dir"]
    artifact_path = ctx.data["artifact_path"]
    job_id = make_job_id("image", host)
    ctx.data["job_id"] = job_id

    # Only path-mode fleetkit needs --override-input to the synced tree.
    override = ""
    if detect_fleetkit_mode(config) == "path":
        inp = fleetkit_input_name(config)
        override = (
            f"--override-input {shlex.quote(inp)} "
            f"path:{shlex.quote(remote_root + '/' + public_name)} "
        )

    inner = (
        f"cd {shlex.quote(remote_root + '/' + inventory_name)}; "
        f"remote_nix={remote_nix}; "
        f"script=$($remote_nix build --print-out-paths "
        f"{override}"
        f".#nixosConfigurations.{shlex.quote(host)}.config.system.build.diskoImagesScript); "
        f"out_dir={shlex.quote(out_dir)}; "
        f"mkdir -p \"$out_dir\"; "
        f"cd \"$out_dir\"; "
        f"\"$script\" --build-memory {int(builder['memory'])}{node_age_key_arg}"
    )

    start_remote_job(builder, job_id, inner, artifact_path=artifact_path)

    status = wait_remote_job(builder, job_id, poll_interval=30)
    if not status.succeeded:
        raise RuntimeError(
            f"remote image build failed (exit_code={status.exit_code}); "
            f"check logs at {job_remote_dir(builder, job_id)}/stderr.log"
        )


def _stage_verify_artifact(ctx: RunContext) -> None:
    """Verify the built image exists and is non-empty."""
    builder = ctx.data["builder"]
    artifact_path = ctx.data["artifact_path"]
    verify_remote_artifact(builder, artifact_path)


def _cleanup_remote_build(ctx: RunContext, reason: str) -> None:
    """Cleanup hook for remote-build stage — does NOT auto-cancel by default.

    The actual cancel/detach decision is made by the interrupt handler in
    the orchestrator.  This hook only runs when explicitly invoked.
    """
    # No-op: cancellation is handled by _execute_interrupt_action.
    pass


def _stage_download(ctx: RunContext) -> None:
    """Download the remote-built image via SCP."""
    builder = ctx.data["builder"]
    artifact_path = ctx.data["artifact_path"]
    output_path = Path(ctx.data["output"])
    if output_path.parent != Path("."):
        output_path.parent.mkdir(parents=True, exist_ok=True)
    run([*scp_args(builder), f"{builder['alias']}:{artifact_path}", str(output_path)])


# ---------------------------------------------------------------------------
# Public command entry points
# ---------------------------------------------------------------------------


def cmd_image(args, config):
    """Build a disko image for *host*.

    Without ``--builder``: local ``nix build``.
    With ``--builder``: remote build (KVM if available, ``--no-kvm`` to force
    non-KVM).
    """
    if not args.builder:
        run(["nix", "build", f".#packages.{args.system}.{args.host}"])
        return

    builder = apply_builder_overrides(builder_config(config, args.builder), args)
    if getattr(args, "no_kvm", False):
        builder["use_kvm"] = False

    if builder["use_kvm"]:
        # KVM remote build via nix build --builders (synchronous, no stages needed).
        env = nix_ssh_env(builder)
        run(
            [
                "nix", "build",
                "--builders", builder_spec(builder, require_kvm=True),
                "--option", "builders-use-substitutes", "true",
                "--max-jobs", "0",
                f".#packages.{args.system}.{args.host}",
            ],
            env=env,
        )
        return

    # Non-KVM remote build — stage-based with structured job monitoring.
    ctx = make_context("image", args.host, args, config)
    ctx.data["builder"] = builder
    ctx.data["out_dir"] = f"{builder['remote_root']}/disko-{args.host}"
    ctx.data["artifact_path"] = f"{ctx.data['out_dir']}/main.raw"

    stages = [
        Stage(name="sync", description="sync worktree to builder", run=_stage_sync, retryable=True),
        Stage(
            name="remote-build",
            description=f"build disko image for {args.host} on builder (non-KVM)",
            run=_stage_remote_build,
            retryable=False,
            destructive=True,
            interrupt_policy="prompt",
        ),
        Stage(
            name="verify-artifact",
            description="verify main.raw exists and is non-empty",
            run=_stage_verify_artifact,
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


def cmd_download_image(args, config):
    """Download a remote-built disko image."""
    builder = apply_builder_overrides(builder_config(config, args.builder), args)
    remote_path = args.remote_path or f"{builder['remote_root']}/disko-{args.host}/main.raw"
    output_path = Path(args.output)
    if output_path.parent != Path("."):
        output_path.parent.mkdir(parents=True, exist_ok=True)
    run([*scp_args(builder), f"{builder['alias']}:{remote_path}", str(output_path)])
