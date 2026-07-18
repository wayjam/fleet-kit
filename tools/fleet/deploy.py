"""`fleet deploy <target>` and `fleet deploy-all`.

With ``--builder``: sync the local worktree to the remote builder and apply
from there (merges the old ``deploy-remote`` recipe).

Remote-builder deploy is split into stages for resume / retry / interactivity:
  sync → lock → apply
"""

import shlex

from builder import (
    apply_builder_overrides,
    builder_config,
    remote_nix_expr,
    remote_shell,
    sync_to_builder,
)
from common import run
from nix import colmena_cmd
from orchestrator import RunContext, Stage, StageRunner, make_context


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


def _stage_sync(ctx: RunContext) -> None:
    builder = ctx.data["builder"]
    sync_to_builder(ctx.config, builder)


def _stage_lock(ctx: RunContext) -> None:
    builder = ctx.data["builder"]
    repos = ctx.config.get("repos", {})
    public_name = repos.get("public_name", "fleet-kit")
    inventory_name = repos.get("inventory_name", "fleet-inventory")
    remote_root = builder["remote_root"]
    remote_nix = remote_nix_expr(builder)
    public_path = shlex.quote(remote_root + "/" + public_name)
    script = (
        f"cd {shlex.quote(remote_root + '/' + inventory_name)}; "
        f"remote_nix={remote_nix}; "
        f"$remote_nix flake lock --override-input fleetkit path:{public_path}"
    )
    remote_shell(builder, script)


def _stage_apply_remote(ctx: RunContext) -> None:
    builder = ctx.data["builder"]
    repos = ctx.config.get("repos", {})
    inventory_name = repos.get("inventory_name", "fleet-inventory")
    remote_root = builder["remote_root"]
    remote_nix = remote_nix_expr(builder)
    on_flag = f" --on {shlex.quote(ctx.data['deploy_target'])}" if ctx.data.get("deploy_target") else ""
    script = (
        f"cd {shlex.quote(remote_root + '/' + inventory_name)}; "
        f"remote_nix={remote_nix}; "
        f"$remote_nix run .#colmena -- --impure --config flake.nix apply{on_flag}"
    )
    remote_shell(builder, script)


def _stage_apply_local(ctx: RunContext) -> None:
    on_args = ["--on", ctx.data["deploy_target"]] if ctx.data.get("deploy_target") else []
    run([*colmena_cmd(), "apply", *on_args])


# ---------------------------------------------------------------------------
# Public command entry points
# ---------------------------------------------------------------------------


def cmd_deploy(args, config):
    if args.builder:
        builder = apply_builder_overrides(builder_config(config, args.builder), args)
        ctx = make_context("deploy", args.target, args, config)
        ctx.data["builder"] = builder
        ctx.data["deploy_target"] = args.target

        stages = [
            Stage(name="sync", description="sync worktree to builder", run=_stage_sync, retryable=True),
            Stage(name="lock", description="flake lock --override-input on builder", run=_stage_lock, retryable=True),
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
        run([*colmena_cmd(), "apply", "--on", args.target])


def cmd_deploy_all(args, config):
    if args.builder:
        builder = apply_builder_overrides(builder_config(config, args.builder), args)
        ctx = make_context("deploy-all", "all", args, config)
        ctx.data["builder"] = builder
        ctx.data["deploy_target"] = None  # apply all hosts

        stages = [
            Stage(name="sync", description="sync worktree to builder", run=_stage_sync, retryable=True),
            Stage(name="lock", description="flake lock --override-input on builder", run=_stage_lock, retryable=True),
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
        run([*colmena_cmd(), "apply"])
