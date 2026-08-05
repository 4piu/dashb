"""Windows per-user startup registration for the Dashb GUI."""

import os
import subprocess
import sys
from pathlib import Path

from dashb.paths import app_root

try:
    import winreg
except ImportError:  # pragma: no cover - winreg only exists on Windows
    winreg = None


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "Dashb"
STARTUP_ARGUMENT = "--startup"


class StartupRegistrationError(RuntimeError):
    """Raised when this platform cannot manage Windows startup registration."""


def is_supported() -> bool:
    return os.name == "nt" and winreg is not None


def startup_argv() -> list[str]:
    """Return an absolute command that works independently of the startup CWD."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), STARTUP_ARGUMENT]

    # Source checkouts are not necessarily installed as a package. Launch the
    # repository's absolute main.py with the current interpreter so Windows does
    # not need a working directory to find `dashb`.
    return [
        str(Path(sys.executable).resolve()),
        str((app_root() / "main.py").resolve()),
        STARTUP_ARGUMENT,
    ]


def startup_command() -> str:
    """Return the correctly quoted command stored in the Windows Run key."""
    return subprocess.list2cmdline(startup_argv())


def registered_command() -> str | None:
    if not is_supported():
        return None

    assert winreg is not None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, _value_type = winreg.QueryValueEx(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        return None
    return value if isinstance(value, str) and value.strip() else None


def is_enabled() -> bool:
    return registered_command() is not None


def set_enabled(enabled: bool) -> None:
    """Add or remove Dashb from the current user's Windows startup apps."""
    if not is_supported():
        if enabled:
            raise StartupRegistrationError(
                "Run on startup is currently supported only on Windows."
            )
        return

    assert winreg is not None
    if enabled:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                RUN_VALUE_NAME,
                0,
                winreg.REG_SZ,
                startup_command(),
            )
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        pass


__all__ = [
    "StartupRegistrationError",
    "is_enabled",
    "is_supported",
    "registered_command",
    "set_enabled",
    "startup_argv",
    "startup_command",
]
