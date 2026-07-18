"""CLI construction and dispatch (`fleet` entry point).

build_parser() wires every subcommand to the cmd_* function in the matching
module; main() loads config and runs the selected command.
"""

import argparse

from age import cmd_age
from build import cmd_build
from builder import add_builder_options, cmd_builder_ping
from deploy import cmd_deploy, cmd_deploy_all
from image import cmd_download_image, cmd_image
from infect import INFECT_STAGES, cmd_infect
from install import cmd_install
from jobs import cmd_jobs
from justfile import cmd_justfile_render
from lxc import cmd_lxc_switch
from misc import cmd_check, cmd_eval, cmd_fmt
from orchestrator import add_orchestration_options
from ports import cmd_ports
from profile import cmd_profile
from secret import cmd_secret

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
    p.add_argument("--kexec-syscall", action="store_true")
    p.add_argument("--yes", action="store_true", help="skip destructive confirmation")
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

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()
    args.func(args, config)
