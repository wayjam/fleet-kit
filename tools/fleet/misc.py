"""Trivial nix-wrapper commands: fmt, check, eval."""

from common import run
from nix import colmena_cmd


def cmd_fmt(_args, _config):
    run(["nix", "fmt"])


def cmd_check(_args, _config):
    run(["nix", "flake", "check", "--show-trace"])


def cmd_eval(_args, _config):
    run([*colmena_cmd(), "eval", "-E", "{ nodes, ... }: builtins.attrNames nodes"])
