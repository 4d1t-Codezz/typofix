"""Picks the keyboard backend for this OS. Everything above this layer is shared."""

import sys


def get_backend():
    if sys.platform == "win32":
        from .windows import Backend
    elif sys.platform == "darwin":
        from .macos import Backend
    else:
        raise RuntimeError("Typofix runs on Windows and macOS.")
    return Backend()
