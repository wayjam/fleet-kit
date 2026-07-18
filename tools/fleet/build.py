"""`fleet build <host>` — build a host system closure.

With ``--builder``: remote build via ``nix build --builders``.
With ``--dry-run``: evaluate without building.
"""

from builder import apply_builder_overrides, builder_config, builder_spec, nix_ssh_env
from common import run
from nix import colmena_cmd


def cmd_build(args, config):
    if args.builder:
        builder = apply_builder_overrides(builder_config(config, args.builder), args)
        env = nix_ssh_env(builder)
        cmd = ["nix", "build"]
        if args.dry_run:
            cmd.append("--dry-run")
        cmd.extend(
            [
                "--builders",
                builder_spec(builder, require_kvm=True),
                "--option",
                "builders-use-substitutes",
                "true",
                "--max-jobs",
                "0",
                f".#packages.x86_64-linux.{args.host}",
            ]
        )
        run(cmd, env=env)
    elif args.dry_run:
        run(["nix", "build", "--dry-run", f".#packages.x86_64-linux.{args.host}"])
    else:
        run([*colmena_cmd(), "build", "--on", args.host])
