"""`fleet build <host>` — build a host system closure.

With ``--builder``: remote build via ``nix build --builders``.
With ``--dry-run``: evaluate without building.
"""

from builder import apply_builder_overrides, builder_config, builder_spec, nix_ssh_env
from common import run
from nix import colmena_cmd


def _system_closure_attr(host):
    return f".#nixosConfigurations.{host}.config.system.build.toplevel"


def cmd_build(args, config):
    target = _system_closure_attr(args.host)
    if args.builder:
        builder = apply_builder_overrides(builder_config(config, args.builder), args)
        env = nix_ssh_env(builder)
        cmd = ["nix", "build"]
        if args.dry_run:
            cmd.append("--dry-run")
        cmd.extend(
            [
                "--builders",
                # `fleet build` builds a system closure, not a VM/test derivation.
                # Honor --no-kvm so ordinary derivations can use a builder without
                # requiring the KVM feature.
                builder_spec(builder, require_kvm=builder["use_kvm"]),
                "--option",
                "builders-use-substitutes",
                "true",
                "--max-jobs",
                "0",
                target,
            ]
        )
        run(cmd, env=env)
    elif args.dry_run:
        run(["nix", "build", "--dry-run", target])
    else:
        run([*colmena_cmd(), "build", "--on", args.host])
