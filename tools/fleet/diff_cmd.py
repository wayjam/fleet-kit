"""`fleet diff <host>` — show what colmena would change (dry-activate)."""

from __future__ import annotations

import subprocess
import sys

from common import die, run
from nix import colmena_cmd


def cmd_diff(args, config):
    host = args.host
    # colmena dry-activate prints planned systemd/unit changes without applying.
    # --impure --config already in colmena_cmd().
    argv = [
        *colmena_cmd(),
        "apply",
        "dry-activate",
        "--on",
        host,
    ]
    if getattr(args, "show_trace", False):
        # colmena passes unknown flags poorly; use verbose via env if needed
        pass
    print(
        f"fleet diff: colmena apply dry-activate --on {host}\n"
        "(no changes applied; review output below)\n",
        file=sys.stderr,
    )
    try:
        run(argv)
    except subprocess.CalledProcessError as exc:
        die(
            f"colmena dry-activate failed (exit {exc.returncode}). "
            "Ensure the host is reachable if buildOnTarget/deploy needs SSH, "
            "or evaluate locally with a matching system."
        )
