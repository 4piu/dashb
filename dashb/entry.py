"""Shared process entry point for both the GUI and the server subprocess it spawns.

A packaged (PyInstaller) build is a single exe with no `python -m` available, so the
GUI relaunches itself with a `--server` flag to run the server instead of spawning a
second interpreter. Running from source takes the same branch via `-m dashb --server`
(see dashb/ui.py's start_server) so both modes share one code path.

`dashb.server` is imported directly (not via runpy's string-based module lookup) so
PyInstaller's static analysis can see and bundle it.
"""


def main(argv: list[str]) -> None:
    if "--server" in argv:
        from dashb.server import run_server

        run_server()
        return

    from dashb.ui import launch_application

    launch_application(argv)
