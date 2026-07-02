"""Filesystem locations that differ between running from source and running as a
PyInstaller-frozen build.
"""

import sys
from pathlib import Path


def app_root() -> Path:
    """Root directory containing bundled resources (web-app/dist, the LHM helper, icons).

    In a PyInstaller onefile build this is the per-launch extraction directory
    (`sys._MEIPASS`); running from source it's the project root two levels up from
    this file (`dashb/paths.py` -> `dashb/` -> project root).
    """
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent
