"""Small terminal styling helpers for fleet's human-readable status output."""

from __future__ import annotations

import os
import sys


_STYLES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "cyan": "36",
}


def color_enabled(stream=None) -> bool:
    """Whether ANSI styling should be emitted to *stream*."""
    stream = stream or sys.stderr
    mode = os.environ.get("FLEET_COLOR", "auto").lower()
    if "NO_COLOR" in os.environ or mode == "never":
        return False
    if mode == "always":
        return True
    if mode != "auto":
        mode = "auto"
    return bool(getattr(stream, "isatty", lambda: False)()) and os.environ.get("TERM") != "dumb"


def styled(text: str, *styles: str, stream=None) -> str:
    """Wrap text in ANSI styles when output is interactive."""
    codes = [_STYLES[style] for style in styles if style in _STYLES]
    if not codes or not color_enabled(stream):
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def status(label: str, message: str, *, level="info", stream=None) -> str:
    """Return a consistently marked status line."""
    styles = {
        "success": ("green", "bold"),
        "error": ("red", "bold"),
        "warning": ("yellow", "bold"),
        "info": ("cyan", "bold"),
        "muted": ("dim",),
    }.get(level, ())
    return f"{styled(label, *styles, stream=stream)} {message}"
