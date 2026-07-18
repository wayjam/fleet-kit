"""Remote-builder resolution, SSH config generation, sync, and builder commands."""

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from common import die, parse_bool, remote_repo_path, repo_path, repo_root, run
from known_hosts import clear_local_known_host


NIX_PROBE = (
    "if command -v nix >/dev/null 2>&1; then "
    "command -v nix; "
    "elif [ -x /nix/var/nix/profiles/default/bin/nix ]; then "
    "printf %s /nix/var/nix/profiles/default/bin/nix; "
    "elif [ -x /root/.nix-profile/bin/nix ]; then "
    "printf %s /root/.nix-profile/bin/nix; "
    "elif [ -x /run/current-system/sw/bin/nix ]; then "
    "printf %s /run/current-system/sw/bin/nix; "
    "else exit 127; fi"
)


def reject_scp_port(value):
    if value and "@" in value and ":" in value.rsplit("@", 1)[1]:
        die(
            "builder addresses must not use scp-style user@host:port; "
            "use --port or fleet.toml port instead"
        )


def split_user_host(value):
    reject_scp_port(value)
    if "@" in value:
        user, host = value.split("@", 1)
        if not user or not host:
            die(f"invalid builder address: {value}")
        return user, host
    return None, value


def looks_like_builder_address(value):
    return (
        "@" in value
        or "." in value
        or ":" in value
        or value in {"localhost", "127.0.0.1", "::1"}
    )


def builder_config(config, name_or_host=None):
    default_name = str(config.get("builder", {}).get("default", "") or "")
    name = name_or_host or default_name
    if not name:
        die("missing builder; pass one or set [builder].default in fleet.toml")

    reject_scp_port(name)
    builders = config.get("builders", {})
    named = dict(builders.get(name, {}))
    if builders and not named and not looks_like_builder_address(name):
        available = ", ".join(sorted(builders))
        suffix = f"; available builders: {available}" if available else ""
        die(f"unknown builder '{name}'{suffix}")

    global_builder = config.get("builder", {})
    paths = config.get("paths", {})

    user_from_arg, host_from_arg = split_user_host(name)
    host = named.get("host") or host_from_arg
    user = named.get("user") or user_from_arg
    port = named.get("port")
    ssh_key = named.get("ssh_key", global_builder.get("ssh_key", "-"))
    ssh_config = named.get("ssh_config", paths.get("ssh_config", "local/ssh-config"))
    remote_root = named.get("remote_root", paths.get("remote_root", "/root"))
    remote_nix = named.get("remote_nix", global_builder.get("remote_nix", "auto"))
    memory = int(named.get("memory", global_builder.get("memory", 768)))
    use_kvm = parse_bool(named.get("use_kvm", global_builder.get("use_kvm", True)))

    use_generated_alias = bool(named or user or port or (ssh_key and ssh_key != "-"))

    return {
        "name": name,
        "alias": ("fleet-builder-" + "".join(c if c.isalnum() else "-" for c in name)) if use_generated_alias else name,
        "use_generated_alias": use_generated_alias,
        "host": host,
        "user": user,
        "port": port,
        "ssh_key": ssh_key,
        "ssh_config": ssh_config,
        "remote_root": str(remote_root),
        "remote_nix": str(remote_nix),
        "memory": memory,
        "use_kvm": use_kvm,
    }


def apply_builder_overrides(builder, args):
    for attr in ("port", "ssh_key", "ssh_config", "remote_root", "remote_nix", "memory"):
        value = getattr(args, attr, None)
        if value is not None:
            builder[attr] = value
    if getattr(args, "kvm", None) is True:
        builder["use_kvm"] = True
    if getattr(args, "no_kvm", None) is True:
        builder["use_kvm"] = False
    return builder


def generated_ssh_config(builder):
    if not builder.get("use_generated_alias"):
        configured = builder.get("ssh_config")
        if configured:
            configured_path = repo_path(configured)
            if configured_path.exists():
                return configured_path
        return None

    configured = builder.get("ssh_config")

    temp = tempfile.NamedTemporaryFile("w", delete=False, prefix="fleet-ssh-", suffix=".config")
    with temp:
        if configured:
            configured_path = repo_path(configured)
            if configured_path.exists():
                temp.write("Include {}\n\n".format(configured_path))
        temp.write("Host {}\n".format(builder["alias"]))
        temp.write("  HostName {}\n".format(builder["host"]))
        if builder.get("user"):
            temp.write("  User {}\n".format(builder["user"]))
        if builder.get("port"):
            temp.write("  Port {}\n".format(builder["port"]))
        if builder.get("ssh_key") and builder["ssh_key"] != "-":
            temp.write("  IdentityFile {}\n".format(Path(builder["ssh_key"]).expanduser()))
        temp.write("  IdentitiesOnly no\n")
        temp.write("  StrictHostKeyChecking accept-new\n")
    return Path(temp.name)


def clear_builder_known_hosts(builder):
    """Remove stale local known_hosts entries for a configured builder."""
    port = builder.get("port")
    for host in dict.fromkeys([builder.get("host"), builder.get("alias"), builder.get("name")]):
        if host:
            clear_local_known_host(host, int(port) if port else None)


def ssh_options():
    return [
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=6",
        "-o", "TCPKeepAlive=yes",
    ]


def ssh_args(builder):
    clear_builder_known_hosts(builder)
    args = ["ssh"]
    config_file = generated_ssh_config(builder)
    if config_file:
        args.extend(["-F", str(config_file)])
    args.extend(ssh_options())
    args.append(builder["alias"])
    return args


def scp_args(builder):
    clear_builder_known_hosts(builder)
    args = ["scp"]
    config_file = generated_ssh_config(builder)
    if config_file:
        args.extend(["-F", str(config_file)])
    args.extend(ssh_options())
    return args


def nix_ssh_env(builder):
    clear_builder_known_hosts(builder)
    env = os.environ.copy()
    config_file = generated_ssh_config(builder)
    ssh_opts = []
    if config_file:
        ssh_opts.extend(["-F", str(config_file)])
    ssh_opts.extend(ssh_options())
    if ssh_opts:
        env["NIX_SSHOPTS"] = " ".join(shlex.quote(part) for part in ssh_opts)
    return env


def builder_ssh_url(builder):
    return f"ssh-ng://{builder['alias']}"


def builder_spec(builder, *, require_kvm=True):
    features = "kvm" if require_kvm else "-"
    return f"{builder_ssh_url(builder)} x86_64-linux {builder['ssh_key']} 1 1 {features} -"


def remote_shell(builder, script):
    run([*ssh_args(builder), "set -eu; " + script])


def remote_nix_expr(builder):
    if builder["remote_nix"] == "auto":
        return f"$({NIX_PROBE})"
    return shlex.quote(builder["remote_nix"])


def sync_to_builder(config, builder):
    repos = config.get("repos", {})
    public_name = repos.get("public_name", "fleet-kit")
    inventory_name = repos.get("inventory_name", "fleet-inventory")
    root = repo_root()
    parent = root.parent
    for name in (public_name, inventory_name):
        if not (parent / name).exists():
            die(f"cannot find sibling repo: {parent / name}")

    remote_root = builder["remote_root"]
    tar_cmd = [
        "tar",
        "-C",
        str(parent),
        "--exclude",
        f"{public_name}/.git",
        "--exclude",
        f"{inventory_name}/.git",
        "--exclude",
        f"{inventory_name}/result",
        "--exclude",
        f"{inventory_name}/result-*",
        "--exclude",
        f"{inventory_name}/main.raw",
        "--exclude",
        f"{inventory_name}/local/keys",
        "-czf",
        "-",
        public_name,
        inventory_name,
    ]
    ssh_cmd = ssh_args(builder) + [
        f"rm -rf {shlex.quote(remote_root + '/' + public_name)} "
        f"{shlex.quote(remote_root + '/' + inventory_name)} "
        f"&& tar -xzf - -C {shlex.quote(remote_root)}"
    ]
    print("+ " + " ".join(shlex.quote(a) for a in tar_cmd) + " | " + " ".join(shlex.quote(a) for a in ssh_cmd), file=sys.stderr)
    tar_proc = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE)
    ssh_proc = subprocess.Popen(ssh_cmd, stdin=tar_proc.stdout)
    assert tar_proc.stdout is not None
    tar_proc.stdout.close()
    ssh_code = ssh_proc.wait()
    tar_code = tar_proc.wait()
    if tar_code != 0:
        raise subprocess.CalledProcessError(tar_code, tar_cmd)
    if ssh_code != 0:
        raise subprocess.CalledProcessError(ssh_code, ssh_cmd)


def normalize_builder_arg(args):
    if getattr(args, "builder_option", None):
        if getattr(args, "builder", None):
            die("pass builder either positionally or with --builder, not both")
        args.builder = args.builder_option
    return args


def add_builder_options(parser, *, include_kvm=False):
    parser.add_argument("--port", type=int)
    parser.add_argument("--ssh-key")
    parser.add_argument("--ssh-config")
    parser.add_argument("--remote-root")
    parser.add_argument("--remote-nix")
    parser.add_argument("--memory", type=int)
    if include_kvm:
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--kvm", action="store_true")
        group.add_argument("--no-kvm", action="store_true")


def cmd_builder_ping(args, config):
    builder = apply_builder_overrides(builder_config(config, args.builder), args)
    env = nix_ssh_env(builder)
    run(["nix", "store", "info", "--store", builder_ssh_url(builder)], env=env)


def cmd_builder_dry_run(args, config):
    builder = apply_builder_overrides(builder_config(config, args.builder), args)
    env = nix_ssh_env(builder)
    run(
        [
            "nix",
            "build",
            "--dry-run",
            "--builders",
            builder_spec(builder, require_kvm=True),
            "--option",
            "builders-use-substitutes",
            "true",
            "--max-jobs",
            "0",
            f".#packages.x86_64-linux.{args.host}",
        ],
        env=env,
    )
