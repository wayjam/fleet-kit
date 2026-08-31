"""CLI construction and dispatch (`fleet` entry point).

build_parser() wires every subcommand to the cmd_* function in the matching
module; main() loads config and runs the selected command.
"""

import argparse

from age import cmd_age
from build import cmd_build
from builder import (
    add_builder_options,
    apply_builder_overrides,
    builder_config,
    cmd_builder_ping,
    sync_to_builder,
)
from deploy import cmd_deploy, cmd_deploy_all
from diff_cmd import cmd_diff
from doctor import cmd_doctor
from image import cmd_download_image, cmd_image
from infect import INFECT_STAGES, cmd_infect
from install import cmd_install
from inventory import cmd_inventory
from jobs import cmd_jobs
from justfile import cmd_justfile_render
from lxc import cmd_lxc_switch
from misc import cmd_check, cmd_eval, cmd_fmt
from orchestrator import add_orchestration_options
from ports import cmd_ports
from profile import cmd_profile
from secret import cmd_secret
from secrets_audit import cmd_secrets_audit
from sops_cmd import cmd_sops
from stale import check_path_fleetkit_stale

from common import load_config


def build_parser():
    parser = argparse.ArgumentParser(prog="fleet")
    sub = parser.add_subparsers(dest="command", required=True)

    # -- fmt / check / eval ---------------------------------------------------
    sub.add_parser("fmt").set_defaults(func=cmd_fmt)
    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("eval").set_defaults(func=cmd_eval)

    # -- build ----------------------------------------------------------------
    p = sub.add_parser("build")
    p.add_argument("host")
    p.add_argument("--builder", default="")
    p.add_argument("--dry-run", action="store_true")
    add_builder_options(p, include_kvm=True)
    p.set_defaults(func=cmd_build)

    # -- builder-ping ---------------------------------------------------------
    p = sub.add_parser("builder-ping")
    p.add_argument("builder", nargs="?")
    add_builder_options(p)
    p.set_defaults(func=cmd_builder_ping)

    # -- deploy / deploy-all --------------------------------------------------
    p = sub.add_parser("deploy")
    p.add_argument("target")
    p.add_argument("--builder", default="")
    add_builder_options(p)
    add_orchestration_options(p)
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("deploy-all")
    p.add_argument("--builder", default="")
    add_builder_options(p)
    add_orchestration_options(p)
    p.set_defaults(func=cmd_deploy_all)

    # -- image / download-image -----------------------------------------------
    p = sub.add_parser("image")
    p.add_argument("host")
    p.add_argument("--builder", default="")
    p.add_argument("--system", default="x86_64-linux")
    add_builder_options(p, include_kvm=True)
    add_orchestration_options(p)
    p.set_defaults(func=cmd_image)

    p = sub.add_parser("download-image")
    p.add_argument("host")
    p.add_argument("--builder", default="")
    p.add_argument("--remote-path")
    p.add_argument("--output", default="main.raw")
    add_builder_options(p)
    p.set_defaults(func=cmd_download_image)

    # -- install --------------------------------------------------------------
    p = sub.add_parser("install")
    p.add_argument("host")
    p.add_argument("--ssh-target", default="root@localhost:22")
    p.add_argument("--build-on", choices=("auto", "remote", "local"), default="auto")
    p.add_argument("--prepare-target", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--kexec-syscall", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--post-kexec-ssh-port", type=int, default=22)
    p.add_argument("--copy-host-keys", action="store_true")
    p.add_argument("--print-build-logs", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true", help="skip destructive confirmation")
    p.add_argument(
        "--backup-ref",
        help="provider backup or snapshot reference recorded before disk installation",
    )
    p.add_argument(
        "--allow-no-backup",
        action="store_true",
        help="explicitly acknowledge that no provider backup reference is available",
    )
    p.add_argument(
        "--retry-destructive",
        action="store_true",
        help="allow interactive retry after a target-state probe and explicit confirmation",
    )
    add_orchestration_options(p)
    p.set_defaults(func=cmd_install)

    # -- infect ---------------------------------------------------------------
    p = sub.add_parser("infect")
    p.add_argument("host")
    p.add_argument("--ssh-target", default=None)
    p.add_argument("--builder", default="")
    p.add_argument("--stage", choices=INFECT_STAGES, default="pre-clean")
    p.add_argument("--stop-after", choices=INFECT_STAGES)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-reboot", action="store_true")
    p.add_argument("--no-deploy", action="store_true")
    p.add_argument("--current-port", type=int)
    p.add_argument("--target-port", type=int)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--nix-channel")
    p.add_argument("--infect-backend", choices=("builder", "nixos-infect"), default="builder")
    add_builder_options(p)
    add_orchestration_options(p, skip_stage_options=True)
    p.set_defaults(func=cmd_infect)

    # -- lxc-switch -----------------------------------------------------------
    p = sub.add_parser("lxc-switch")
    p.add_argument("host")
    p.set_defaults(func=cmd_lxc_switch)

    # -- ports ----------------------------------------------------------------
    p = sub.add_parser("ports")
    p.add_argument("host")
    p.set_defaults(func=cmd_ports)

    # -- profile --------------------------------------------------------------
    p = sub.add_parser("profile")
    p.add_argument("host")
    p.add_argument("--kind", choices=("all", "xray", "sing-box", "hy2", "wireguard"), default="all")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--inbound", help="Xray inbound name")
    p.add_argument("--interface", help="WireGuard interface name")
    p.add_argument("--host", dest="host_address", help="Client-facing server address; defaults to colmena targetHost")
    p.add_argument("--name", help="URI fragment label for URI-based profiles")
    p.add_argument("--fingerprint", default="chrome", help="Reality uTLS fingerprint")
    p.set_defaults(func=cmd_profile, uri_only=False)

    # -- age ------------------------------------------------------------------
    age = sub.add_parser("age")
    age_sub = age.add_subparsers(dest="age_command", required=True)
    for name in ("list", "read", "edit", "create"):
        p = age_sub.add_parser(name)
        p.add_argument("target")
        p.add_argument("rest", nargs="*")
        p.set_defaults(func=cmd_age)

    # -- secret ---------------------------------------------------------------
    secret = sub.add_parser("secret")
    secret_sub = secret.add_subparsers(dest="secret_command", required=True)
    secret_sub.add_parser("uuid").set_defaults(func=cmd_secret)
    p = secret_sub.add_parser("password")
    p.add_argument("--length", default=32, type=int)
    p.add_argument("--mode", default="plain", choices=("plain", "ss2022"))
    p.set_defaults(func=cmd_secret)
    p = secret_sub.add_parser("hex")
    p.add_argument("--bytes", default=32, type=int)
    p.set_defaults(func=cmd_secret)
    p = secret_sub.add_parser("randstr")
    p.add_argument("--bytes", default=16, type=int)
    p.add_argument("--prefix", default="")
    p.set_defaults(func=cmd_secret)
    p = secret_sub.add_parser("xray-shortid")
    p.add_argument("--bytes", default=8, type=int)
    p.set_defaults(func=cmd_secret)
    secret_sub.add_parser("xray-reality").set_defaults(func=cmd_secret)
    secret_sub.add_parser("age").set_defaults(func=cmd_secret)
    p = secret_sub.add_parser("age-file")
    p.add_argument("name")
    p.set_defaults(func=cmd_secret)
    secret_sub.add_parser("wireguard").set_defaults(func=cmd_secret)
    p = secret_sub.add_parser("ssh")
    p.add_argument("name")
    p.add_argument("--comment", default="operator@example.invalid")
    p.set_defaults(func=cmd_secret)
    secret_sub.add_parser("proxy").set_defaults(func=cmd_secret)

    # -- jobs -----------------------------------------------------------------
    p = sub.add_parser("jobs")
    jobs_sub = p.add_subparsers(dest="jobs_command", required=True)

    p = jobs_sub.add_parser("list")
    p.add_argument("--builder", default="")
    add_builder_options(p)
    p.set_defaults(func=cmd_jobs)

    p = jobs_sub.add_parser("status")
    p.add_argument("job_id")
    p.add_argument("--builder", default="")
    add_builder_options(p)
    p.set_defaults(func=cmd_jobs)

    p = jobs_sub.add_parser("log")
    p.add_argument("job_id")
    p.add_argument("--builder", default="")
    p.add_argument("--which", choices=("stdout", "stderr"), default="stderr")
    p.add_argument("--lines", type=int, default=50)
    add_builder_options(p)
    p.set_defaults(func=cmd_jobs)

    p = jobs_sub.add_parser("cancel")
    p.add_argument("job_id")
    p.add_argument("--builder", default="")
    p.add_argument("--force", action="store_true")
    add_builder_options(p)
    p.set_defaults(func=cmd_jobs)

    p = jobs_sub.add_parser("cleanup")
    p.add_argument("--builder", default="")
    p.add_argument("--older-than", type=int, default=7)
    add_builder_options(p)
    p.set_defaults(func=cmd_jobs)

    # -- justfile render ------------------------------------------------------
    justfile = sub.add_parser("justfile")
    justfile_sub = justfile.add_subparsers(dest="justfile_command", required=True)
    p = justfile_sub.add_parser("render")
    p.add_argument("--output", default="-")
    p.set_defaults(func=cmd_justfile_render)

    # -- inventory (init / list / add-host / doctor) ---------------------------
    inventory = sub.add_parser(
        "inventory",
        help="private inventory helpers (init, list, add-host, doctor)",
    )
    inventory_sub = inventory.add_subparsers(dest="inventory_command", required=True)

    p = inventory_sub.add_parser(
        "init",
        help="scaffold a private inventory from templates/fleet-inventory",
    )
    p.add_argument(
        "directory",
        nargs="?",
        default="fleet-private",
        help="destination directory (default: fleet-private)",
    )
    p.add_argument(
        "--fleetkit-url",
        default="",
        help='flake input URL for fleetkit (default: path:../fleet-kit)',
    )
    p.add_argument(
        "--name",
        default="",
        help="repos.inventory_name in fleet.toml (default: destination directory name)",
    )
    p.add_argument(
        "--git",
        action="store_true",
        help="run git init in the new directory",
    )
    p.add_argument(
        "--lock",
        action="store_true",
        help="run nix flake lock after scaffolding",
    )
    p.set_defaults(func=cmd_inventory)

    p = inventory_sub.add_parser("list", help="list nixos hosts in hosts/default.nix")
    p.set_defaults(func=cmd_inventory)

    p = inventory_sub.add_parser(
        "add-host",
        help="add a host skeleton and register it in hosts/default.nix",
    )
    p.add_argument("host", help="inventory key / hostname (e.g. aws-sg2)")
    p.add_argument(
        "--kind",
        choices=("proxy", "image"),
        default="proxy",
        help="host skeleton kind (default: proxy)",
    )
    p.add_argument("--target-host", default="", help="deployment.targetHost (default placeholder)")
    p.add_argument("--target-port", type=int, default=2234)
    p.add_argument("--target-user", default="root")
    p.add_argument("--tag", action="append", default=[], help="deployment tag (repeatable)")
    p.add_argument(
        "--image",
        action="store_true",
        help="set image = true even for proxy kind",
    )
    p.add_argument(
        "--from-template",
        action="store_true",
        help="copy hosts/proxy-example or image-example instead of minimal skeleton",
    )
    p.set_defaults(func=cmd_inventory)

    p = inventory_sub.add_parser(
        "doctor",
        help="check inventory layout, fleetkit input, secrets tracking",
    )
    p.set_defaults(func=cmd_inventory)

    p = inventory_sub.add_parser(
        "skills-link",
        help="symlink skills/* to fleet-kit/skills and .claude/skills -> ../skills",
    )
    p.set_defaults(func=cmd_inventory)

    # -- doctor ---------------------------------------------------------------
    p = sub.add_parser("doctor", help="diagnose inventory, lock, and builder")
    p.add_argument(
        "doctor_target",
        nargs="?",
        default="all",
        choices=("all", "inventory", "builder"),
        help="what to check (default: all)",
    )
    p.add_argument("--builder", default="")
    add_builder_options(p)
    p.set_defaults(func=cmd_doctor)

    # -- sync -----------------------------------------------------------------
    p = sub.add_parser("sync", help="sync worktree to remote builder")
    p.add_argument("--builder", default="")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print fleetkit_mode/sync_method/repos only; do not transfer",
    )
    add_builder_options(p)
    p.set_defaults(func=cmd_sync)

    # -- secrets audit --------------------------------------------------------
    p = sub.add_parser("secrets", help="secret file helpers")
    secrets_sub = p.add_subparsers(dest="secrets_command", required=True)
    p = secrets_sub.add_parser(
        "audit",
        help="compare sops.secrets declarations vs secrets/*.yaml keys",
    )
    p.add_argument("--host", default="", help="limit to one host")
    p.set_defaults(func=cmd_secrets_audit_entry)

    # -- sops rekey / rotate-hint ---------------------------------------------
    p = sub.add_parser("sops", help="sops maintenance (rekey, rotate checklist)")
    sops_sub = p.add_subparsers(dest="sops_command", required=True)
    p = sops_sub.add_parser(
        "rekey",
        help="sops updatekeys on secrets (after .sops.yaml recipient change)",
    )
    p.add_argument("--host", default="", help="only this host's secrets/<host>.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_sops)
    p = sops_sub.add_parser(
        "rotate-hint",
        help="print age key rotation checklist (no automatic rewrite)",
    )
    p.set_defaults(func=cmd_sops)

    # -- diff -----------------------------------------------------------------
    p = sub.add_parser("diff", help="colmena dry-activate for one host")
    p.add_argument("host")
    p.set_defaults(func=cmd_diff)

    return parser


def cmd_sync(args, config):
    name = args.builder or None
    if name == "":
        name = None
    builder = apply_builder_overrides(builder_config(config, name), args)
    sync_to_builder(config, builder, dry_run=bool(args.dry_run))


def cmd_secrets_audit_entry(args, config):
    if not getattr(args, "host", None):
        args.host = None
    elif args.host == "":
        args.host = None
    return cmd_secrets_audit(args, config)


def main():
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()
    # Warn when path fleetkit lock is older than the on-disk kit tree.
    # Skip for pure scaffolding that may run outside an inventory.
    cmd = getattr(args, "command", None)
    if cmd not in {"inventory"} or getattr(args, "inventory_command", None) != "init":
        check_path_fleetkit_stale(config)
    args.func(args, config)
