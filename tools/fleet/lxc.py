"""`fleet lxc switch`."""

from common import run


def cmd_lxc_switch(args, _config):
    run(["system-manager", "switch", "--sudo", "--flake", f".#{args.host}"])
