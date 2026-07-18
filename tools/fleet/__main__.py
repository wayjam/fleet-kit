#!/usr/bin/env python3
"""`fleet` entry point.

Invoked as `python3 tools/fleet` (the flake wraps exactly that), which runs this
module. Sibling modules are imported by absolute name because `tools/fleet` is
prepended to sys.path when Python runs a directory.
"""

import subprocess
import sys

from cli import main


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"error: command exited {exc.returncode}", file=sys.stderr)
        sys.exit(exc.returncode)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
